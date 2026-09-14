"""Canonical index counts and external observations retain separate authority."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.authority import AuthorityPaths
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.conftest import cli_text

FINANCIAL = ("transactions", "rules", "assets", "goals", "scenarios")
ORDER = (
    "transactions",
    "rules",
    "reports",
    "journals",
    "templates",
    "assets",
    "goals",
    "scenarios",
)


def _index(root: QueryRoot, *options: str, legacy=False, human=False, evidence=True):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "index",
            *options,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider} if evidence and not legacy else {},
    )


def _payload(result):
    assert result.exit_code == 0, cli_text(result)
    return json.loads(cli_text(result))


def _collections(payload):
    return {item["name"]: item for item in payload["collections"]}


def _hashes(root: Path):
    lock = AuthorityPaths.for_data_dir(root).coordination_lock
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path != lock
    }


def test_index_migration_counts_order_schema_paths_and_readonly(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    before = _hashes(root.root)
    old = _collections(_payload(_index(root, legacy=True)))
    result = _index(root, "--include-paths")
    payload = _payload(result)
    collections = _collections(payload)
    assert tuple(collections) == ORDER
    for name in ("transactions", "rules", "goals"):
        assert collections[name]["count"] == old[name]["count"]
    for name in FINANCIAL:
        entry = collections[name]
        assert entry["path"] is None and entry["path_included"] is False
        assert entry["latest_modified"] is None
        assert entry["basis"] == "repository"
        assert entry["type"] == (
            "repository_rows" if name in {"transactions", "assets"} else "repository_config"
        )
    meta = payload["_meta"]["repository"]
    assert meta["dataset_generation"] == root.generation
    assert meta["dataset_revision"] == 0
    assert meta["calculation_policy"] == "canonical_index_counts.v1"
    _validate_command_schema(payload, command="index", schema_file="index.schema.json")
    human = _index(root, human=True)
    assert human.exit_code == 0, cli_text(human)
    assert "Repository revision: 0" in cli_text(human)
    assert "finjuice init" not in cli_text(human)
    assert _hashes(root.root) == before


def test_index_ignores_live_financial_files(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    before = _collections(_payload(_index(root)))
    for relative in (
        "transactions/2026/08/transactions.csv",
        "rules.yaml",
        "goals.yaml",
        "scenarios.yaml",
        "assets/2026/08/balance.csv",
    ):
        path = root.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_LIVE_POISON: [", encoding="utf-8")
    result = _index(root)
    after = _collections(_payload(result))
    for name in FINANCIAL:
        assert after[name] == before[name]
    assert "PRIVATE_LIVE_POISON" not in cli_text(result)


@pytest.mark.parametrize("state", ["invalid", "unselected", "empty_document"])
def test_index_unknown_goals_survive_compact_without_zero_or_init(tmp_path, state):
    source = _source(tmp_path)
    goals = source / "goals.yaml"
    if state == "unselected":
        (source / "nested").mkdir()
        goals.rename(source / "nested" / "goals.yaml")
    else:
        goals.write_text("{}" if state == "empty_document" else "PRIVATE_GOALS: [")
    root = _activate(source, tmp_path)
    raw = _payload(_index(root))
    compact = _payload(_index(root, "--privacy", "compact"))
    for payload in (raw, compact):
        entry = _collections(payload)["goals"]
        assert entry["exists"] is True
        assert entry["count"] is None and entry["status"] == "unavailable"
        assert entry["count_state"] == "unavailable"
        assert entry["basis"] == "repository"
        assert entry["count_basis"] and entry["unavailable_reason"]
        assert entry["selection_state"] == ("unselected" if state == "unselected" else "selected")
        assert "revision_id" in entry
        assert payload["workspace"]["status"] == "incomplete"
        assert "finjuice init" not in json.dumps(payload)
        assert "PRIVATE_GOALS" not in json.dumps(payload)
        _validate_command_schema(payload, command="index", schema_file="index.schema.json")


def test_index_empty_rows_and_absent_required_rules_are_distinct(tmp_path):
    source = _source(tmp_path)
    shutil.rmtree(source / "transactions")
    (source / "rules.yaml").unlink()
    root = _activate(source, tmp_path)
    payload = _payload(_index(root))
    entries = _collections(payload)
    assert entries["transactions"]["exists"] is True
    assert entries["transactions"]["count"] == 0
    assert entries["transactions"]["count_state"] == "known"
    assert entries["transactions"]["status"] == "empty"
    assert entries["rules"]["exists"] is False
    assert entries["rules"]["count"] is None
    assert entries["rules"]["status"] == "missing"
    assert entries["rules"]["count_state"] == "absent"
    assert payload["workspace"]["status"] == "incomplete"
    assert "finjuice init" not in json.dumps(payload)


@pytest.mark.parametrize("failure", ["missing_evidence", "corrupt_pointer"])
def test_index_authority_failure_is_static_without_legacy_fallback(tmp_path, failure):
    root = _activate(_source(tmp_path), tmp_path)
    (root.root / "rules.yaml").write_text("PRIVATE_FALLBACK: [")
    if failure == "corrupt_pointer":
        AuthorityPaths.for_data_dir(root.root).activation.write_text("PRIVATE_POINTER: [")
    result = _index(root, evidence=failure != "missing_evidence")
    assert result.exit_code != 0
    assert "PRIVATE" not in cli_text(result)
    payload = json.loads(cli_text(result))
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "collections" not in payload


def test_index_external_reports_and_journals_are_separate_observations(tmp_path, monkeypatch):
    root = _activate(_source(tmp_path), tmp_path)
    journal_dir = tmp_path / "external-journals"
    journal_dir.mkdir()
    monkeypatch.setenv("FINJUICE_JOURNAL_DIR", str(journal_dir))
    (journal_dir / "old.md").write_text("PRIVATE_JOURNAL_CONTENT")
    reports = Config(data_dir=root.root).reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "report.txt").write_text("PRIVATE_REPORT_CONTENT")
    (reports / "other.txt").write_text("PRIVATE_OTHER_CONTENT")
    before = _hashes(root.root), _hashes(journal_dir)
    result = _index(root, "--include-paths")
    payload = _payload(result)
    entries = _collections(payload)
    assert entries["reports"]["count"] == 2
    assert entries["journals"]["count"] == 1
    assert entries["reports"]["basis"] == "filesystem_observation"
    assert entries["journals"]["basis"] == "filesystem_observation"
    assert entries["templates"]["basis"] == "runtime_inventory"
    observations = payload["_meta"]["observations"]
    assert observations["basis"] == "external_runtime_observations"
    assert datetime.fromisoformat(observations["started_at"]) <= datetime.fromisoformat(
        observations["completed_at"]
    )
    assert payload["_meta"]["repository"]["dataset_revision"] == 0
    assert "PRIVATE" not in cli_text(result)
    assert (_hashes(root.root), _hashes(journal_dir)) == before


def test_index_unreadable_external_reports_keeps_canonical_counts(tmp_path, monkeypatch):
    from finjuice.pipeline.cli.commands import index_repository

    root = _activate(_source(tmp_path), tmp_path)

    def inaccessible(*args, **kwargs):
        raise OSError("PRIVATE_OBSERVATION_FAILURE")

    monkeypatch.setattr(index_repository, "_reports_collection", inaccessible)
    result = _index(root)
    payload = _payload(result)
    entries = _collections(payload)
    assert entries["transactions"]["count"] == 1
    report = entries["reports"]
    assert report["status"] == report["count_state"] == "unavailable"
    assert report["exists"] is None and report["count"] is None
    assert report["path"] is None
    assert report["basis"] == "filesystem_observation"
    assert report["unavailable_reason"] == "filesystem_observation_failed"
    assert payload["workspace"]["status"] == "incomplete"
    assert "PRIVATE_OBSERVATION_FAILURE" not in cli_text(result)
    assert "finjuice init" not in cli_text(result)
    _validate_command_schema(payload, command="index", schema_file="index.schema.json")
