"""Actual canonical doctor diagnoses evidence without falling back to live files."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.doctor import checks
from finjuice.pipeline.doctor.models import CheckResult
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import query_root as _query_fixture
from tests.test_json_schemas import _load_schema, _validator_for

query_root = _query_fixture


@pytest.fixture(autouse=True)
def observed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        checks,
        "_check_skill_runtime",
        lambda: [CheckResult("ok", "Synthetic external runtime", name="synthetic_runtime")],
    )
    monkeypatch.setattr(checks, "_check_dependencies", lambda: [])
    monkeypatch.setattr(checks, "_check_analytics_duckdb", lambda: ([], [], None))


def _doctor(root, *, human: bool = False, evidence: bool = True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "doctor", *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider} if evidence else {},
    )


def _payload(result):
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator_for(_load_schema("doctor.schema.json")).validate(payload)
    assert payload["summary"]["total"] == len(payload["checks"])
    assert payload["summary"]["errors"] == sum(row["status"] == "fail" for row in payload["checks"])
    assert any(row["name"] == "synthetic_runtime" for row in payload["checks"])
    return payload


def test_canonical_doctor_ignores_live_data_and_preserves_existing_probe(query_root) -> None:
    for relative in (
        "rules.yaml",
        "metadata/import_history.csv",
        "metadata/schema.yaml",
        "transactions/2026/09/transactions.csv",
    ):
        target = query_root.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_SENTINEL: broken\n")
    probe = query_root.root / ".doctor_test"
    probe.write_bytes(b"existing-user-file")

    result = _doctor(query_root)
    payload = _payload(result)

    assert "PRIVATE_SENTINEL" not in result.output
    assert payload["_meta"]["authority"] == "repository"
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["_meta"]["dataset_generation"] == query_root.generation
    assert payload["_meta"]["transaction_total"] == 2
    assert payload["_meta"]["date_min"] == "2026-09-01"
    by_name = {row["name"]: row for row in payload["checks"]}
    assert by_name["repository_transactions"]["basis"] == "repository"
    assert by_name["synthetic_runtime"]["basis"] == "runtime_observation"
    assert by_name["repository_staged_imports"]["basis"] == "staged_observation"
    observation = payload["_meta"]["runtime_observation"]
    assert observation["observation_started_at"] <= observation["observation_completed_at"]
    assert not any(row["name"] == "data_directory_structure" for row in payload["checks"])
    assert probe.read_bytes() == b"existing-user-file"
    human = _doctor(query_root, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output
    assert "별도 관측" in human.output
    assert probe.read_bytes() == b"existing-user-file"


def test_missing_activation_is_diagnostic_failure_without_csv_fallback(
    query_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINJUICE_SQLITE_GENERATION", query_root.generation)
    result = _doctor(query_root, evidence=False)
    payload = _payload(result)
    assert payload["summary"]["errors"] > 0
    assert payload["_meta"]["authority"] == "unavailable"
    assert any(row["status"] == "fail" for row in payload["checks"])
    assert "Canonical data unavailable" in _doctor(query_root, human=True, evidence=False).output


def test_empty_repository_is_distinct_from_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("rules: []\n")
    root = _activate(source, tmp_path)
    payload = _payload(_doctor(root))
    assert payload["_meta"]["authority"] == "repository"
    assert payload["summary"]["errors"] == 0
    assert not any(row["name"] == "data_directory_structure" for row in payload["checks"])


def test_invalid_canonical_rules_never_expose_source_or_use_live_rules(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("rules: [PRIVATE_SENTINEL\n")
    root = _activate(source, tmp_path)
    (root.root / "rules.yaml").write_text("rules: []\n")
    result = _doctor(root)
    payload = _payload(result)
    assert payload["summary"]["errors"] > 0
    assert "PRIVATE_SENTINEL" not in result.output + caplog.text


def test_incomplete_transactions_preserve_rules_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "source"
    partition = source / "transactions/2026/01/transactions.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("amount,amount\n1,2\n")
    (source / "rules.yaml").write_text("rules: []\n")
    (source / "goals.yaml").write_text("goals: invalid-semantic-value\n")
    root = _activate(source, tmp_path)
    payload = _payload(_doctor(root))
    by_name = {row["name"]: row for row in payload["checks"]}
    assert by_name["repository_transactions"]["status"] == "fail"
    assert by_name["repository_rules"]["status"] == "pass"
    assert payload["_meta"]["transaction_total"] is None
    assert payload["_meta"]["date_min"] is None
    assert payload["_meta"]["transaction_state"] == "incomplete"


def test_native_staged_completion_is_observed_against_pinned_revision(tmp_path: Path) -> None:
    from tests.cli.commands.test_repository_history_native import _native_root

    root, command, *_ = _native_root(tmp_path)
    staged = root.root / "imports/PRIVATE_SENTINEL.xlsx"
    staged.parent.mkdir()
    staged.write_bytes(command.capture.source_bytes)
    result = _doctor(root)
    payload = _payload(result)
    metadata = payload["_meta"]
    assert metadata["dataset_revision"] == 1
    assert metadata["transaction_total"] == 1
    assert metadata["staged_observation"]["already_imported_files"] == 1
    assert metadata["staged_observation"]["pending_files"] == 0
    assert "PRIVATE_SENTINEL" not in result.output
