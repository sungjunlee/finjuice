"""Canonical context actual-migration parity, authority, and unavailable contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.authority import AuthorityPaths
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.conftest import cli_text
from tests.pipeline.checkup.helpers import _tx_row, write_transactions

FINANCIAL_SECTIONS = (
    "status_snapshot",
    "active_goals",
    "financial_metadata",
    "rule_notes",
    "top_patterns",
)
GOALS_FIELDS = (
    "structural_savings_monthly_avg",
    "structural_savings_transaction_monthly_avg",
    "recurring_savings_monthly_amount",
    "structural_savings_sources",
    "monthly_avg_consumption_expense",
    "consumption_savings_rate_3mo",
)


def _context(root: QueryRoot, *options: str, legacy=False, human=False, evidence=True):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "context",
            "--journal",
            "0",
            "--budget",
            "100000",
            *options,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider} if evidence and not legacy else {},
    )


def _payload(result):
    assert result.exit_code == 0, cli_text(result)
    return json.loads(cli_text(result))


def _financial_source(tmp_path: Path) -> Path:
    source = _source(tmp_path)
    with (source / "goals.yaml").open("a", encoding="utf-8") as stream:
        stream.write("financial_context:\n  income:\n    monthly_estimate: 500000\n")
    (source / "rules.yaml").write_text(
        "version: 1\nrules:\n  - name: context-note\n"
        "    match: SYNTHETIC_MERCHANT\n    fields: [merchant_raw]\n"
        "    tags: [food]\n    notes: synthetic context note\n",
        encoding="utf-8",
    )
    return source


def _goals_root(tmp_path: Path, state: str) -> QueryRoot:
    source = _financial_source(tmp_path)
    goals = source / "goals.yaml"
    if state == "invalid":
        goals.write_text("PRIVATE_GOALS_SENTINEL: [", encoding="utf-8")
    elif state == "unselected":
        nested = source / "nested" / "goals.yaml"
        nested.parent.mkdir()
        goals.rename(nested)
    elif state == "absent":
        goals.unlink()
    return _activate(source, tmp_path)


def _file_hashes(root: Path) -> dict[str, str]:
    lock = AuthorityPaths.for_data_dir(root).coordination_lock
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path != lock
    }


def test_context_migration_financial_parity_schema_revision_and_readonly(tmp_path: Path):
    root = _activate(_financial_source(tmp_path), tmp_path)
    before = _file_hashes(root.root)
    old = _payload(_context(root, legacy=True))
    new = _payload(_context(root))
    for section in FINANCIAL_SECTIONS:
        assert new[section] == old[section], section
    assert new["rule_notes"][0]["notes"] == "synthetic context note"
    assert new["active_goals"] and new["financial_metadata"]
    assert new["top_patterns"]
    meta = new["_meta"]["repository"]
    assert str(UUID(meta["dataset_generation"])) == root.generation
    assert meta["dataset_revision"] == 0
    assert meta["calculation_policy"] == "legacy_context_snapshot.v1"
    assert meta["goals_state"] == "valid"
    assert new["_meta"]["journals_basis"] == "external_historical_observations"
    _validate_command_schema(new, command="context", schema_file="context.schema.json")
    human = _context(root, human=True)
    assert human.exit_code == 0, cli_text(human)
    assert "Repository revision: 0" in cli_text(human)
    assert "synthetic context note" in cli_text(human)
    assert _file_hashes(root.root) == before


def test_context_live_transaction_and_configuration_poison_is_ignored(tmp_path: Path):
    root = _activate(_financial_source(tmp_path), tmp_path)
    before = _payload(_context(root))
    for relative in ("transactions/2026/08/transactions.csv", "goals.yaml", "rules.yaml"):
        path = root.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_LIVE_POISON: [", encoding="utf-8")
    result = _context(root)
    after = _payload(result)
    for section in FINANCIAL_SECTIONS:
        assert after[section] == before[section]
    assert after["_meta"]["repository"] == before["_meta"]["repository"]
    assert "PRIVATE_LIVE_POISON" not in cli_text(result)


@pytest.mark.parametrize("state", ["invalid", "unselected"])
def test_context_unknown_goals_are_nullable_with_static_warning(tmp_path: Path, state: str):
    root = _goals_root(tmp_path, state)
    result = _context(root)
    payload = _payload(result)
    assert payload["active_goals"] is None
    assert payload["financial_metadata"] is None
    status = payload["status_snapshot"]
    assert status["active_goals"] is None and status["financial_metadata"] is None
    assert all(status[field] is None for field in GOALS_FIELDS)
    assert status["monthly_avg_expense"] == 120000
    assert payload["top_patterns"]
    assert payload["_meta"]["repository"]["goals_state"] == "unavailable"
    assert payload["_meta"]["warnings"]
    assert "PRIVATE_GOALS_SENTINEL" not in cli_text(result)
    _validate_command_schema(payload, command="context", schema_file="context.schema.json")
    human = _context(root, human=True)
    assert human.exit_code == 0, cli_text(human)
    assert "Active Goals\n- unavailable" in cli_text(human)
    assert "Financial Metadata\n- unavailable" in cli_text(human)
    assert "PRIVATE_GOALS_SENTINEL" not in cli_text(human)


def test_context_proven_absent_goals_are_empty_not_unknown(tmp_path: Path):
    payload = _payload(_context(_goals_root(tmp_path, "absent")))
    assert payload["active_goals"] == []
    assert payload["financial_metadata"] == {}
    assert payload["_meta"]["repository"]["goals_state"] == "absent"
    assert payload["_meta"]["warnings"] == []
    _validate_command_schema(payload, command="context", schema_file="context.schema.json")


@pytest.mark.parametrize("human", [False, True])
def test_context_primary_unmaterialized_source_is_static_failure(tmp_path: Path, human: bool):
    source = _financial_source(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01",
                -987654,
                "PRIVATE_INCOMPLETE",
                category_final="food",
                tags_final="PRIVATE_BAD_TAG[",
            )
        ],
    )
    root = _activate(source, tmp_path)
    result = _context(root, human=human)
    assert result.exit_code != 0
    assert "PRIVATE" not in cli_text(result)
    assert "987654" not in cli_text(result)
    if not human:
        payload = json.loads(cli_text(result))
        assert payload["error"]["code"] == "VALIDATION_FAILED"
        assert "status_snapshot" not in payload


@pytest.mark.parametrize("state", ["invalid", "unselected"])
def test_context_low_budget_keeps_unknown_warning_and_revision(tmp_path: Path, state: str):
    root = _goals_root(tmp_path, state)
    full = _payload(_context(root))
    small = _payload(_context(root, "--budget", "1"))
    assert small["_meta"]["truncated"] is True
    assert small["_meta"]["warnings"] == full["_meta"]["warnings"]
    assert small["_meta"]["repository"] == full["_meta"]["repository"]
    assert small["active_goals"] is None and small["financial_metadata"] is None
    assert small["status_snapshot"]["active_goals"] is None
    assert small["_meta"]["dropped_sections"][0] == "top_patterns"
    assert "active_goals" not in small["_meta"]["dropped_sections"]
    assert small["_meta"]["token_estimate_policy"] == (
        "content_characters_divided_by_four_soft_budget.v1"
    )
    _validate_command_schema(small, command="context", schema_file="context.schema.json")


@pytest.mark.parametrize("human", [False, True])
def test_context_present_activation_without_provider_has_no_fallback(tmp_path: Path, human: bool):
    root = _activate(_financial_source(tmp_path), tmp_path)
    write_transactions(
        root.root,
        "2026-07",
        [
            _tx_row(
                "2026-07-12", -123456, "PRIVATE_FALLBACK", category_final="food", tags_final="[]"
            )
        ],
    )
    result = _context(root, evidence=False, human=human)
    assert result.exit_code != 0
    assert "PRIVATE_FALLBACK" not in cli_text(result)
    if not human:
        payload = json.loads(cli_text(result))
        assert payload["error"]["code"] == "VALIDATION_FAILED"
        assert "status_snapshot" not in payload


HISTORICAL_GENERATION = "00000000-0000-4000-8000-000000000007"


def _historical_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    journal_dir = tmp_path / "historical-journals"
    journal_dir.mkdir()
    monkeypatch.setenv("FINJUICE_JOURNAL_DIR", str(journal_dir))
    note = journal_dir / "2026-07-01_historical.md"
    note.write_text(
        "---\ncreated: '2026-07-01T09:00:00+09:00'\ntopic: historical\n"
        "data_range: '2026-06-01 ~ 2026-06-30'\nsnapshot:\n"
        "  monthly_avg_income: null\n  savings_rate_3mo: null\n"
        "snapshot_metadata:\n"
        f"  dataset_generation: '{HISTORICAL_GENERATION}'\n"
        "  dataset_revision: 7\n"
        "  unavailable_fields: [monthly_avg_income, savings_rate_3mo]\n"
        "  unknown_private_key: PRIVATE_METADATA_SENTINEL\n"
        "  arbitrary_nested: {secret: PRIVATE_NESTED_SENTINEL}\n"
        "---\nHistorical observation.\n",
        encoding="utf-8",
    )
    return note


def test_context_historical_journal_keeps_own_revision_and_unknown_snapshot(tmp_path, monkeypatch):
    root = _activate(_financial_source(tmp_path), tmp_path)
    note = _historical_note(tmp_path, monkeypatch)
    original = note.read_bytes()
    result = _context(root, "--journal", "1")
    payload = _payload(result)
    assert payload["_meta"]["repository"]["dataset_revision"] == 0
    assert payload["_meta"]["repository"]["dataset_generation"] == root.generation
    entry = payload["journals"][0]
    assert entry["snapshot_metadata"]["dataset_generation"] == HISTORICAL_GENERATION
    assert entry["snapshot_metadata"]["dataset_revision"] == 7
    assert entry["snapshot_metadata_basis"] == "historical_journal_observation"
    assert entry["snapshot"] == {"monthly_avg_income": None, "savings_rate_3mo": None}
    assert entry["snapshot_metadata"]["unavailable_fields"] == [
        "monthly_avg_income",
        "savings_rate_3mo",
    ]
    assert "unknown_private_key" not in entry["snapshot_metadata"]
    assert "arbitrary_nested" not in entry["snapshot_metadata"]
    assert "PRIVATE_METADATA_SENTINEL" not in cli_text(result)
    assert "PRIVATE_NESTED_SENTINEL" not in cli_text(result)
    assert note.read_bytes() == original
    _validate_command_schema(payload, command="context", schema_file="context.schema.json")


def test_context_low_budget_records_historical_journal_drop(tmp_path, monkeypatch):
    root = _activate(_financial_source(tmp_path), tmp_path)
    note = _historical_note(tmp_path, monkeypatch)
    original = note.read_bytes()
    payload = _payload(_context(root, "--journal", "1", "--budget", "1"))
    assert payload["journals"] == []
    assert payload["_meta"]["dropped_sections"][:2] == ["top_patterns", f"journals:{note.name}"]
    assert payload["_meta"]["repository"]["dataset_revision"] == 0
    assert payload["_meta"]["journals_basis"] == "external_historical_observations"
    assert note.read_bytes() == original
    _validate_command_schema(payload, command="context", schema_file="context.schema.json")


@pytest.mark.parametrize("human", [False, True])
def test_context_missing_duckdb_preserves_goals_and_marks_patterns_unavailable(
    tmp_path, monkeypatch, human
):
    import builtins

    root = _activate(_financial_source(tmp_path), tmp_path)
    original_import = builtins.__import__

    def without_duckdb(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("PRIVATE_EXCEPTION")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", without_duckdb)
        result = _context(root, human=human)

    assert result.exit_code == 0, cli_text(result)
    assert "PRIVATE_EXCEPTION" not in cli_text(result)
    if human:
        assert "Top Patterns\n- unavailable" in cli_text(result)
        assert "Monthly budget:" in cli_text(result)
        assert "Warning:" in cli_text(result)
        assert "finjuice doctor" in cli_text(result)
    else:
        payload = _payload(result)
        assert payload["active_goals"]
        assert payload["financial_metadata"]
        assert payload["top_patterns"] is None
        repository = payload["_meta"]["repository"]
        assert repository["goals_state"] == "valid"
        assert repository["top_patterns_state"] == "unavailable"
        assert "top_patterns" in repository["unavailable_fields"]
        assert payload["_meta"]["warnings"]
        assert any("finjuice doctor" in message for message in payload["_meta"]["warnings"])
        _validate_command_schema(payload, command="context", schema_file="context.schema.json")
