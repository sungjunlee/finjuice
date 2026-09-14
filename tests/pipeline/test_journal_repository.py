"""Canonical journal snapshots retain provenance without live input fallback."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline import journal_repository as adapter
from finjuice.pipeline.analysis_source import read_analysis_source
from finjuice.pipeline.config import Config
from finjuice.pipeline.insights import collect_status_snapshot
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions
from tests.pipeline.test_sqlite_exact_import import _tx_book
from tests.pipeline.test_sqlite_exact_import import _tx_row as _workbook_row


@pytest.fixture
def active(tmp_path: Path) -> QueryRoot:
    source = init_data_dir(tmp_path, "source")
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row("2026-09-01", 1000, "salary", category_final="income", tags_final="[]"),
            _tx_row("2026-09-02", -200, "shop", category_final="food", tags_final="[]"),
        ],
    )
    return _activate(source, tmp_path)


def _collect(active: QueryRoot):
    result = adapter.collect_repository_journal_snapshot(
        Config(data_dir=active.root), active.provider
    )
    assert result is not None
    return result


def test_actual_migration_parity_and_live_poison(active: QueryRoot) -> None:
    legacy = collect_status_snapshot(Config(data_dir=active.legacy))
    before = _collect(active)
    assert before.snapshot == legacy.snapshot
    assert before.metadata["goals_state"] == "absent"
    assert before.metadata["unavailable_fields"] == ["active_goals"]
    assert before.metadata["calculation_as_of"] is None
    (active.root / "goals.yaml").write_text("PRIVATE: [")
    (active.root / "rules.yaml").write_text("PRIVATE: [")
    (active.legacy / "rules.yaml").write_text("PRIVATE: [")
    assert _collect(active) == before


@pytest.mark.parametrize("state", ["invalid", "unselected", "schema"])
def test_goals_unavailable_fields_do_not_claim_zero(active: QueryRoot, state: str) -> None:
    StorageMutationFacade(active.root, active.provider).replace_config(
        ConfigDocument(
            "goals",
            b"PRIVATE: [" if state != "invalid" else b"{}",
            "parsed" if state == "schema" else "invalid",
            None,
            "test.v1",
        )
    )
    snapshot = read_analysis_source(active.root, active.provider)
    assert snapshot is not None
    if state == "unselected":
        snapshot = replace(
            snapshot, goals=replace(snapshot.goals, head=None, selection_state="unselected")
        )
    result = adapter.journal_snapshot_from_analysis(snapshot)
    assert result.warning is not None
    assert result.metadata["goals_state"] == "unavailable"
    assert set(result.metadata["unavailable_fields"]) == {
        "active_goals",
        "structural_savings_monthly_avg",
        "structural_savings_transaction_monthly_avg",
        "recurring_savings_monthly_amount",
        "structural_savings_sources",
        "monthly_avg_consumption_expense",
        "consumption_savings_rate_3mo",
    }
    assert "PRIVATE" not in str(result.metadata) + result.warning
    assert result.snapshot.monthly_avg_income == 1000


@pytest.mark.parametrize("state", ["invalid", "unselected", "filters"])
def test_rules_selection_is_strict(active: QueryRoot, state: str) -> None:
    snapshot = read_analysis_source(active.root, active.provider)
    assert snapshot is not None and snapshot.rules.head is not None
    selection = snapshot.rules
    if state == "unselected":
        selection = replace(selection, head=None, selection_state="unselected")
    else:
        selection = replace(
            selection,
            head=replace(
                selection.head,
                content=b"rules: []\nreport_filters: PRIVATE\n"
                if state == "filters"
                else b"rules: []\n",
                parsed_status="invalid" if state == "invalid" else "parsed",
            ),
        )
    with pytest.raises(adapter.RepositoryJournalError, match="Canonical journal snapshot"):
        adapter.journal_snapshot_from_analysis(replace(snapshot, rules=selection))


def test_filters_count_is_applied_and_pin_survives_mutation(active: QueryRoot, monkeypatch) -> None:
    before = _collect(active)
    original = adapter.read_analysis_source
    calls = 0

    def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(active.root, active.provider).replace_config(
            ConfigDocument(
                "rules",
                b"rules: []\nreport_filters:\n  excluded_categories:\n"
                b"    - name: food\n      reason: test\n",
                "parsed",
                None,
                "test.v1",
            )
        )
        return snapshot

    monkeypatch.setattr(adapter, "read_analysis_source", read)
    assert _collect(active) == before
    assert calls == 1
    monkeypatch.setattr(adapter, "read_analysis_source", original)
    fresh = _collect(active)
    assert fresh.metadata["dataset_revision"] == before.metadata["dataset_revision"] + 1
    assert fresh.snapshot.active_filters == 1
    assert fresh.snapshot.monthly_avg_expense == 0


def test_incomplete_and_missing_authority_fail_before_snapshot(
    active: QueryRoot, tmp_path: Path
) -> None:
    with pytest.raises(adapter.RepositoryJournalError):
        adapter.collect_repository_journal_snapshot(Config(data_dir=active.root), None)
    source = init_data_dir(tmp_path, "opaque-source")
    path = source / "transactions/2026/09/transactions.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount,amount\n1,2\n")
    other = _activate(source, tmp_path / "opaque-build")
    with pytest.raises(adapter.RepositoryJournalError):
        _collect(other)


def test_native_and_detached_aux_scope(active: QueryRoot) -> None:
    from finjuice.pipeline.storage.sqlite.transaction_scopes import TransactionScope

    StorageMutationFacade(active.root, active.provider).import_exact_xlsx(
        ExactImportCommand(
            capture_exact_xlsx(_tx_book(_workbook_row(2)), filename="synthetic.xlsx")
        )
    )
    snapshot = read_analysis_source(active.root, active.provider)
    assert snapshot is not None
    before = adapter.journal_snapshot_from_analysis(snapshot)
    row = {**snapshot.transactions.rows[0], "transaction_id": "aux", "amount": "-999999999"}
    transactions = replace(
        snapshot.transactions,
        rows=(*snapshot.transactions.rows, row),
        scopes=(
            *snapshot.transactions.scopes,
            TransactionScope("aux", "2026-09", False),
        ),
    )
    assert (
        adapter.journal_snapshot_from_analysis(replace(snapshot, transactions=transactions))
        == before
    )
    assert any(row["row_hash"] is None for row in snapshot.transactions.rows)


@pytest.mark.parametrize("amount", ["1e999", "1e308"])
def test_nonfinite_input_or_sum_is_rejected(active: QueryRoot, amount: str) -> None:
    snapshot = read_analysis_source(active.root, active.provider)
    assert snapshot is not None
    rows = tuple({**row, "amount": amount} for row in snapshot.transactions.rows)
    snapshot = replace(snapshot, transactions=replace(snapshot.transactions, rows=rows))
    with pytest.raises(adapter.RepositoryJournalError, match="Canonical journal snapshot"):
        adapter.journal_snapshot_from_analysis(snapshot)


def test_selected_goals_preserve_recurring_and_tag_alias_computation(active: QueryRoot) -> None:
    from tests.pipeline.test_insights_repository import GOALS

    StorageMutationFacade(active.root, active.provider).replace_config(
        ConfigDocument("goals", GOALS, "parsed", None, "test.v1")
    )
    snapshot = read_analysis_source(active.root, active.provider)
    assert snapshot is not None
    rows = tuple({**row, "tags_final": '["saving"]'} for row in snapshot.transactions.rows)
    snapshot = replace(snapshot, transactions=replace(snapshot.transactions, rows=rows))
    result = adapter.journal_snapshot_from_analysis(snapshot)
    assert result.warning is None
    assert result.metadata["goals_state"] == "valid"
    assert result.snapshot.recurring_savings_monthly_amount == 100
    assert result.snapshot.structural_savings_transaction_monthly_avg == 200
    assert result.snapshot.monthly_avg_consumption_expense == 0
    assert result.snapshot.structural_savings_monthly_avg == 300
    assert result.metadata["unavailable_fields"] == ["active_goals"]


def test_empty_canonical_and_absent_rules_are_valid(tmp_path: Path) -> None:
    source = init_data_dir(tmp_path, "source")
    (source / "rules.yaml").unlink()
    active = _activate(source, tmp_path)
    result = _collect(active)
    assert result.metadata["rules_selection_state"] == "absent"
    assert result.snapshot.data_range is None
    assert result.snapshot.active_filters == 0
    assert result.warning is None
