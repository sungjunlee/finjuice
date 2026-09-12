"""CLI wiring and privacy boundaries for inactive preservation migration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.backup import BackupError
from finjuice.pipeline.cli import main
from finjuice.pipeline.cli.commands import ssot_migrate
from finjuice.pipeline.migration import MigrationError, MigrationResult

runner = CliRunner()
DIGEST = "sha256:" + "a" * 64
PRIVATE = "private-account-transactions.csv"


def _payload() -> MigrationResult:
    return MigrationResult(
        {
            "status": "ok",
            "phase": "migration_plan",
            "manifest_digest": DIGEST,
            "input_count": 3,
            "plan": {"path": PRIVATE, "amount": "123456.78"},
            "raw_rows": [PRIVATE],
            "limitations": [PRIVATE],
            "checks": {"database_integrity": "passed", PRIVATE: "passed"},
        }
    )


@pytest.mark.parametrize("json_output", [True, False])
@pytest.mark.parametrize("with_output", [True, False])
def test_plan_passes_optional_output_and_hides_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool, with_output: bool
) -> None:
    # Arrange: mocked private evidence must never become public output.
    operation = Mock(return_value=_payload())
    monkeypatch.setattr(ssot_migrate, "plan_migration", operation)
    manifest = tmp_path / PRIVATE
    plan = tmp_path / "private-plan.json"
    args = ["ssot", "migrate", "plan", "--manifest", str(manifest)]
    if with_output:
        args.extend(["--output", str(plan)])
    if json_output:
        args.append("--json")

    # Act.
    result = runner.invoke(main.app, args)

    # Assert.
    assert result.exit_code == 0, result.output
    operation.assert_called_once_with(manifest, output=plan if with_output else None)
    assert PRIVATE not in result.output
    assert "123456.78" not in result.output
    assert str(tmp_path) not in result.output
    if json_output:
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "ssot migrate plan"
        assert payload["input_count"] == 3
        assert payload["manifest_digest"] == DIGEST
        assert payload["cutover_ready"] is False
        assert payload["checks"] == {"database_integrity": "passed"}
        assert "plan" not in payload
    else:
        assert "Migration ok" in result.output
        assert "not ready" in result.output


@pytest.mark.parametrize("json_output", [True, False])
def test_build_passes_active_data_directory_and_retry_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool
) -> None:
    # Arrange.
    operation = Mock(return_value=MigrationResult({"status": "already_complete"}))
    monkeypatch.setattr(ssot_migrate, "build_migration", operation)
    active = tmp_path / "active"
    plan = tmp_path / "plan.json"
    staging = tmp_path / "candidate"
    parent = "b" * 32
    args = [
        "--data-dir",
        str(active),
        "ssot",
        "migrate",
        "build",
        "--plan",
        str(plan),
        "--staging",
        str(staging),
        "--parent-attempt-id",
        parent,
    ]
    if json_output:
        args.append("--json")

    # Act.
    result = runner.invoke(main.app, args)

    # Assert: uninitialized active paths still protect inactive builds.
    assert result.exit_code == 0, result.output
    operation.assert_called_once_with(
        plan, staging, active_data_dir=active, parent_attempt_id=parent
    )
    assert "already_complete" in result.output
    assert str(tmp_path) not in result.output


@pytest.mark.parametrize("json_output", [True, False])
def test_build_fails_closed_when_active_directory_resolution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool
) -> None:
    # Arrange.
    operation = Mock()
    monkeypatch.setattr(ssot_migrate, "build_migration", operation)
    monkeypatch.setattr(main, "_resolve_active_data_dir", lambda _: None)
    args = [
        "ssot",
        "migrate",
        "build",
        "--plan",
        str(tmp_path / PRIVATE),
        "--staging",
        str(tmp_path / "candidate"),
    ]
    if json_output:
        args.append("--json")

    # Act.
    result = runner.invoke(main.app, args)

    # Assert.
    assert result.exit_code == 3
    operation.assert_not_called()
    assert "Migration validation failed" in result.output
    assert PRIVATE not in result.output
    assert not (tmp_path / "candidate").exists()


@pytest.mark.parametrize("json_output", [True, False])
def test_verify_works_without_initialized_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool
) -> None:
    # Arrange.
    candidate = tmp_path / PRIVATE
    operation = Mock(return_value=_payload())
    monkeypatch.setattr(ssot_migrate, "verify_migration", operation)
    monkeypatch.setattr(main, "_resolve_active_data_dir", lambda _: None)
    args = ["ssot", "migrate", "verify", "--candidate", str(candidate)]
    if json_output:
        args.append("--json")

    # Act.
    result = runner.invoke(main.app, args)

    # Assert.
    assert result.exit_code == 0, result.output
    operation.assert_called_once_with(candidate)
    assert PRIVATE not in result.output
    if json_output:
        assert json.loads(result.output)["_meta"]["command"] == "ssot migrate verify"


@pytest.mark.parametrize("json_output", [True, False])
@pytest.mark.parametrize(
    ("exception", "exit_code"),
    [
        (MigrationError(PRIVATE), 3),
        (BackupError(PRIVATE), 3),
        (OSError(PRIVATE), 1),
        (RuntimeError(PRIVATE), 1),
    ],
)
def test_errors_hide_private_exception_details(
    monkeypatch: pytest.MonkeyPatch, json_output: bool, exception: Exception, exit_code: int
) -> None:
    # Arrange.
    monkeypatch.setattr(ssot_migrate, "verify_migration", Mock(side_effect=exception))
    args = ["ssot", "migrate", "verify", "--candidate", PRIVATE]
    if json_output:
        args.append("--json")

    # Act.
    result = runner.invoke(main.app, args)

    # Assert.
    assert result.exit_code == exit_code, result.output
    assert PRIVATE not in result.output
    if json_output:
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "ssot migrate verify"
        assert payload["error"]["code"] in {"VALIDATION_FAILED", "UNEXPECTED_ERROR"}


def test_public_summary_rejects_private_values_inside_known_fields() -> None:
    # Arrange.
    result = MigrationResult(
        {
            "status": PRIVATE,
            "phase": [PRIVATE],
            "manifest_digest": PRIVATE,
            "attempt_id": PRIVATE,
            "input_count": PRIVATE,
            "dataset_revision": True,
            "cutover_ready": True,
            "checks": {"object_hashes": PRIVATE},
        }
    )

    # Act.
    public = ssot_migrate._public_summary(result)

    # Assert.
    assert PRIVATE not in json.dumps(public)
    assert public["cutover_ready"] is False
    assert "dataset_revision" not in public
    assert public["checks"] == {}
