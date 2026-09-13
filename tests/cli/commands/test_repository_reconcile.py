"""Canonical reconciliation uses immutable exact payments and explicit UUID identity."""

import hashlib
import json
import shutil
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.authority import AuthorityPaths
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


def _evidence(tmp_path, *, amount="120000", when="2026-07-12", currency="KRW"):
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "occurred_on": when,
                        "amount": amount,
                        "currency": currency,
                    }
                ]
            }
        )
    )
    return path


def _invoke(root, evidence, *, legacy=False, human=False, provider=True):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "reconcile",
            "--evidence",
            str(evidence),
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider} if provider and not legacy else {},
    )


def _tree_bytes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path != AuthorityPaths.for_data_dir(root).coordination_lock
    }


def test_reconcile_small_amount_parity_uuid_and_no_writes(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    evidence = _evidence(tmp_path)
    before, evidence_before = _tree_bytes(root.root), evidence.read_bytes()
    old, new = _invoke(root, evidence, legacy=True), _invoke(root, evidence)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    legacy, canonical = json.loads(old.output), json.loads(new.output)
    for key in ("evidence_count", "payment_count", "matched", "partial", "unmatched"):
        assert canonical[key] == legacy[key]
    _validate_command_schema(canonical, command="reconcile", schema_file="reconcile.schema.json")
    assert canonical["matched"] == 1
    for item in canonical["groups"][0]["payment_ids"]:
        assert str(UUID(item)) == item
    assert canonical["_meta"]["dataset_revision"] == 0
    assert (
        canonical["_meta"]["evidence_input"]["sha256"]
        == hashlib.sha256(evidence_before).hexdigest()
    )
    assert canonical["groups"][0]["status"] == legacy["groups"][0]["status"]
    assert Decimal(canonical["groups"][0]["residual"]) == Decimal(legacy["groups"][0]["residual"])
    assert _tree_bytes(root.root) == before
    assert evidence.read_bytes() == evidence_before
    human = _invoke(root, evidence, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision: 0" in human.output
    assert "UUID" in human.output


def test_reconcile_ignores_live_csv_goals_and_rules(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    evidence = _evidence(tmp_path)
    first = _invoke(root, evidence)
    assert first.exit_code == 0, first.output
    for relative in ("transactions/2026/07/transactions.csv", "rules.yaml", "goals.yaml"):
        path = root.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_POISON: [\n")
    result = _invoke(root, evidence)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["groups"] == json.loads(first.output)["groups"]
    assert "PRIVATE_POISON" not in result.output


@pytest.mark.parametrize("empty", [True, False])
def test_reconcile_empty_or_missing_month_is_unmatched(tmp_path, empty):
    source = _source(tmp_path)
    if empty:
        shutil.rmtree(source / "transactions")
        (source / "transactions").mkdir()
    root = _activate(source, tmp_path)
    result = _invoke(root, _evidence(tmp_path, when="2024-01-01"))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["payment_count"] == (0 if empty else 1)
    assert payload["unmatched"] == 1
    assert payload["groups"][0]["payment_ids"] == []


@pytest.mark.parametrize("human", [False, True])
@pytest.mark.parametrize("bad", ["PRIVATE_DATE", "NaN", "Infinity"])
def test_reconcile_invalid_evidence_is_static(tmp_path, bad, human):
    root = _activate(_source(tmp_path), tmp_path)
    evidence = (
        _evidence(tmp_path, when=bad) if bad == "PRIVATE_DATE" else _evidence(tmp_path, amount=bad)
    )
    result = _invoke(root, evidence, human=human)
    assert result.exit_code != 0
    if not human:
        assert json.loads(result.output)["error"]["code"] == "VALIDATION_FAILED"
    assert bad not in result.output


def test_reconcile_missing_authority_evidence_has_no_fallback(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    write_transactions(
        root.root,
        "2026-07",
        [
            _tx_row(
                "2026-07-12", -120000, "PRIVATE_FALLBACK", category_final="food", tags_final="[]"
            )
        ],
    )
    result = _invoke(root, _evidence(tmp_path), provider=False)
    assert result.exit_code != 0
    assert "PRIVATE_FALLBACK" not in result.output
    assert "payment_count" not in json.loads(result.output)


def test_reconcile_large_exact_payment_under_small_decimal_context(tmp_path):
    amount = "90071992547409931234567890123456789.0123"
    source = _source(tmp_path)
    row = _tx_row("2026-07-12", -1, "precise", category_final="food", tags_final="[]")
    row["amount"] = "-" + amount
    write_transactions(source, "2026-08", [row])
    root = _activate(source, tmp_path)
    with localcontext() as context:
        context.prec = 3
        result = _invoke(root, _evidence(tmp_path, amount=amount))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["matched"] == 1
    assert Decimal(payload["groups"][0]["residual"]) == 0


def test_reconcile_duplicate_aliases_do_not_collapse_payments(tmp_path):
    source = _source(tmp_path)
    rows = [
        _tx_row(
            "2026-07-12",
            -value,
            f"merchant-{value}",
            category_final="food",
            tags_final="[]",
            row_hash="duplicate-alias",
        )
        for value in (100, 200)
    ]
    write_transactions(source, "2026-08", rows)
    root = _activate(source, tmp_path)
    result = _invoke(root, _evidence(tmp_path, amount="300"))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["payment_count"] == 2
    ids = payload["groups"][0]["payment_ids"]
    assert len(ids) == len(set(ids)) == 2
    assert all(str(UUID(item)) == item for item in ids)


def test_reconcile_native_payment_without_row_hash_uses_uuid(tmp_path, monkeypatch):
    from dataclasses import replace

    from finjuice.pipeline.storage.authority import AuthorityPaths, StaticActivationEvidenceProvider
    from finjuice.pipeline.storage.sqlite import RepositoryBuilder, RepositoryReader
    from tests.cli.commands.test_repository_query import QueryRoot
    from tests.pipeline.test_sqlite_bulk_mutations import _evidence as host_evidence
    from tests.pipeline.test_sqlite_bulk_mutations import _write_activation
    from tests.pipeline.test_sqlite_transaction_scopes import _native

    add = RepositoryBuilder.add_transaction

    def dated_transaction(builder, record):
        return add(builder, replace(record, date_raw="2026-09-01"))

    with monkeypatch.context() as context:
        context.setattr(RepositoryBuilder, "add_transaction", dated_transaction)
        candidate = _native(tmp_path, ["2026-09-01"])
    with RepositoryReader(candidate.database) as reader:
        generation = reader.info.dataset_generation
        rows = reader.transaction_snapshot().rows
    assert len(rows) == 1 and rows[0]["row_hash"] is None
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    shutil.copytree(candidate.root, paths.generation(generation).root)
    _write_activation(paths, generation)
    case = QueryRoot(
        root, tmp_path / "unused", StaticActivationEvidenceProvider(host_evidence()), generation
    )
    result = _invoke(case, _evidence(tmp_path, amount="1", when="2026-09-01", currency="USD"))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["matched"] == 1
    assert payload["groups"][0]["payment_ids"] == [rows[0]["transaction_id"]]
    assert payload["_meta"]["payment_identity_policy"] == "transaction_uuid.v1"


@pytest.mark.parametrize("human", [False, True])
def test_reconcile_unmaterialized_source_fails_before_partial_matching(tmp_path, human):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01",
                -987654,
                "PRIVATE_INCOMPLETE",
                category_final="food",
                tags_final="PRIVATE_TAG[",
            )
        ],
    )
    root = _activate(source, tmp_path)
    result = _invoke(root, _evidence(tmp_path), human=human)
    assert result.exit_code != 0
    assert "PRIVATE" not in result.output
    assert "987654" not in result.output
    if not human:
        assert json.loads(result.output)["error"]["code"] == "VALIDATION_FAILED"
        assert "payment_count" not in json.loads(result.output)


@pytest.mark.parametrize("window_days", [0, 1])
def test_reconcile_records_window_that_controls_matching(tmp_path, window_days):
    root = _activate(_source(tmp_path), tmp_path)
    evidence = _evidence(tmp_path, when="2026-07-13")
    result = CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.root),
            "reconcile",
            "--evidence",
            str(evidence),
            "--window-days",
            str(window_days),
            "--json",
        ],
        obj={"activation_evidence_provider": root.provider},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["matched"] == window_days
    assert payload["_meta"]["window_days"] == window_days


@pytest.mark.parametrize(
    ("evidence_amount", "payment_amount", "payment_count"),
    [(7, -13, 5), (100, -1, 16)],
)
def test_reconcile_keeps_normal_matches_with_impossible_leftover_sums(
    tmp_path, evidence_amount, payment_amount, payment_count
):
    source = _source(tmp_path)
    amounts = [-(3000 + index) for index in range(30)] + [payment_amount] * payment_count
    rows = [
        _tx_row(
            "2026-07-12",
            amount,
            f"payment-{index}",
            row_hash=f"payment-{index}",
            category_final="food",
            tags_final="[]",
        )
        for index, amount in enumerate(amounts)
    ]
    write_transactions(source, "2026-07", rows)
    root = _activate(source, tmp_path)
    evidence = _evidence(tmp_path)
    evidence.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidence_id": f"e-{index}",
                        "occurred_on": "2026-07-12",
                        "amount": str(amount),
                        "currency": "KRW",
                    }
                    for index, amount in enumerate(list(range(3000, 3030)) + [evidence_amount] * 20)
                ]
            }
        )
    )
    result = _invoke(root, evidence)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["matched"] == 30
    assert payload["unmatched"] == 20
    assert payload["payment_count"] == 31 + payment_count  # Includes the August partition.
