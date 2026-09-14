"""Canonical payment readers retain exact identity and amounts without live fallback."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID

import pytest

from finjuice.pipeline.reconcile import repository as adapter
from finjuice.pipeline.reconcile.payments import payments_from_ledger
from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot
from finjuice.pipeline.storage.sqlite.exact import MAX_COEFFICIENT_DIGITS, ExactValue
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions
from tests.pipeline.test_journal_repository import active as _active_fixture
from tests.pipeline.test_sqlite_exact_import import _tx_book
from tests.pipeline.test_sqlite_exact_import import _tx_row as _workbook_row

active = _active_fixture


def _collect(active: QueryRoot):
    result = adapter.read_repository_payments(active.root, active.provider)
    assert result is not None
    return result


def test_actual_migration_parity_and_live_poison(active: QueryRoot) -> None:
    legacy = payments_from_ledger(active.legacy / "transactions")
    result = _collect(active)
    assert sorted((p.occurred_on, p.amount, p.currency) for p in result.payments) == sorted(
        (p.occurred_on, p.amount, p.currency) for p in legacy
    )
    assert all(str(UUID(p.payment_id)) == p.payment_id for p in result.payments)
    (active.root / "rules.yaml").write_text("PRIVATE: [")
    (active.root / "goals.yaml").write_text("PRIVATE: [")
    (active.legacy / "transactions/2026/09/transactions.csv").write_text("PRIVATE")
    assert _collect(active) == result


def test_duplicate_aliases_and_invalid_configs_do_not_remove_payments(tmp_path: Path) -> None:
    source = init_data_dir(tmp_path, "source")
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01", -10, "one", category_final="food", tags_final="[]", row_hash="same"
            ),
            _tx_row(
                "2026-09-02", -20, "two", category_final="food", tags_final="[]", row_hash="same"
            ),
        ],
    )
    (source / "rules.yaml").write_text("PRIVATE: [")
    (source / "goals.yaml").write_text("PRIVATE: [")
    active = _activate(source, tmp_path)
    result = _collect(active)
    assert len(result.payments) == len({p.payment_id for p in result.payments}) == 2
    assert sorted(p.amount for p in result.payments) == [Decimal(-20), Decimal(-10)]


def test_single_snapshot_native_import_after_detach_is_pinned(
    active: QueryRoot, monkeypatch
) -> None:
    original = adapter.read_transaction_snapshot
    before = _collect(active)
    calls = 0

    def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(active.root, active.provider).import_exact_xlsx(
            ExactImportCommand(capture_exact_xlsx(_tx_book(_workbook_row(2)), filename="test.xlsx"))
        )
        return snapshot

    monkeypatch.setattr(adapter, "read_transaction_snapshot", read)
    assert _collect(active) == before
    assert calls == 1
    monkeypatch.setattr(adapter, "read_transaction_snapshot", original)
    fresh = _collect(active)
    assert len(fresh.payments) == len(before.payments) + 1
    assert fresh.metadata["dataset_revision"] == before.metadata["dataset_revision"] + 1
    snapshot = original(active.root, active.provider)
    assert snapshot is not None
    native_ids = {row["transaction_id"] for row in snapshot.rows if row["row_hash"] is None}
    assert native_ids and native_ids <= {p.payment_id for p in fresh.payments}


@pytest.mark.parametrize(
    "lexical",
    [
        "9007199254740993.0100",
        "12345678901234567890123456789.00001",
        "-0.00",
        "0." + "0" * 254 + "1",
    ],
)
def test_exact_amount_is_independent_of_decimal_context(active: QueryRoot, lexical: str) -> None:
    snapshot = read_transaction_snapshot(active.root, active.provider)
    assert snapshot is not None
    value = ExactValue.from_lexical(lexical, value_kind="money", currency="KRW")
    rows = tuple(
        {
            **row,
            "amount": lexical,
            "amount_coefficient": value.coefficient,
            "amount_scale": value.scale,
            "amount_lexical": lexical,
        }
        for row in snapshot.rows
    )
    with localcontext() as context:
        context.prec = 3
        context.Emax = 9
        context.Emin = -9
        result = adapter.payments_from_snapshot(replace(snapshot, rows=rows))
    assert all(p.amount.as_tuple() == Decimal(lexical).as_tuple() for p in result.payments)


@pytest.mark.parametrize("damage", ["currency", "date", "amount", "scale", "digits", "scope"])
def test_invalid_evidence_never_silently_skips(active: QueryRoot, damage: str) -> None:
    snapshot = read_transaction_snapshot(active.root, active.provider)
    assert snapshot is not None
    row = dict(snapshot.rows[0])
    if damage == "currency":
        row.update(currency=None, currency_unknown=True)
    elif damage == "date":
        row["date"] = "PRIVATE_BAD_DATE"
    elif damage == "amount":
        row["amount"] = "Infinity"
    elif damage == "scale":
        row["amount_scale"] = 256
    elif damage == "digits":
        row["amount_coefficient"] = "1" * (MAX_COEFFICIENT_DIGITS + 1)
        row["amount_lexical"] = None
    else:
        snapshot = replace(snapshot, scopes=())
    with pytest.raises(adapter.RepositoryReconcileError, match="Canonical reconciliation") as error:
        adapter.payments_from_snapshot(replace(snapshot, rows=(row, *snapshot.rows[1:])))
    assert "PRIVATE" not in str(error.value)


def test_auxiliary_unsupported_row_is_excluded(active: QueryRoot) -> None:
    snapshot = read_transaction_snapshot(active.root, active.provider)
    assert snapshot is not None
    scopes = tuple(replace(scope, included=False) for scope in snapshot.scopes)
    rows = tuple({**row, "date": None, "currency_unknown": True} for row in snapshot.rows)
    result = adapter.payments_from_snapshot(replace(snapshot, rows=rows, scopes=scopes))
    assert result.payments == ()
    assert result.metadata["excluded_scope_count"] == len(rows)


@pytest.mark.parametrize("opaque", [False, True])
def test_empty_is_valid_but_opaque_is_not(tmp_path: Path, opaque: bool) -> None:
    source = init_data_dir(tmp_path, "source")
    path = source / "transactions/2026/09/transactions.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount,amount\n1,2\n" if opaque else "row_hash,date,amount\n")
    active = _activate(source, tmp_path)
    if opaque:
        with pytest.raises(adapter.RepositoryReconcileError):
            _collect(active)
    else:
        assert _collect(active).payments == ()


def test_verified_legacy_and_authority_failure(active: QueryRoot, tmp_path: Path) -> None:
    assert adapter.read_repository_payments(tmp_path / "legacy", None) is None
    with pytest.raises(adapter.RepositoryReconcileError):
        adapter.read_repository_payments(active.root, None)


def test_public_exact_digit_bound_is_supported_without_integer_conversion(
    active: QueryRoot,
) -> None:
    snapshot = read_transaction_snapshot(active.root, active.provider)
    assert snapshot is not None
    lexical = "1" * MAX_COEFFICIENT_DIGITS
    rows = tuple(
        {
            **row,
            "amount": lexical,
            "amount_coefficient": lexical,
            "amount_scale": 0,
            "amount_lexical": lexical,
            "date": "2026-09-01T12:30:00",
        }
        for row in snapshot.rows
    )
    result = adapter.payments_from_snapshot(replace(snapshot, rows=rows))
    assert all(
        len(payment.amount.as_tuple().digits) == MAX_COEFFICIENT_DIGITS
        for payment in result.payments
    )
    assert all(payment.occurred_on.isoformat() == "2026-09-01" for payment in result.payments)
