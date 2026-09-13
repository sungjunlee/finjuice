"""CLI tests for SQLite generation backup create/restore/status."""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder

runner = CliRunner()


def _generation(tmp_path: Path) -> Path:
    paths = GenerationPaths(tmp_path / "generation")
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        builder.publish_source(io.BytesIO(b"cli sqlite backup source"))
        builder.finalize()
    return paths.root


def test_ssot_backup_json_round_trip_hides_paths(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    backup = tmp_path / "backup"
    created = runner.invoke(
        app,
        [
            "ssot",
            "backup",
            "create",
            "--source",
            str(source),
            "--output",
            str(backup),
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    payload = json.loads(created.output)
    assert payload["_meta"]["command"] == "ssot backup create"
    assert payload["status"] == "complete"
    assert payload["complete"] is True
    assert str(source) not in created.output
    assert str(backup) not in created.output

    status = runner.invoke(app, ["ssot", "backup", "status", str(backup), "--json"])
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["complete"] is True
    assert status_payload["_meta"]["command"] == "ssot backup status"

    target = tmp_path / "restored"
    restored = runner.invoke(
        app,
        ["ssot", "backup", "restore", str(backup), "--target", str(target), "--json"],
    )
    assert restored.exit_code == 0, restored.output
    restore_payload = json.loads(restored.output)
    assert restore_payload["status"] == "restored"
    assert restore_payload["generation_status"] == "inactive"
    assert str(target) not in restored.output
    assert (target / "finjuice.sqlite3").is_file()


def test_ssot_backup_restore_refuses_active_data_dir(tmp_path: Path) -> None:
    source = _generation(tmp_path)
    backup = tmp_path / "backup"
    created = runner.invoke(
        app,
        [
            "ssot",
            "backup",
            "create",
            "--source",
            str(source),
            "--output",
            str(backup),
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(source),
            "ssot",
            "backup",
            "restore",
            str(backup),
            "--target",
            str(source),
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert "isolated" in payload["error"]["message"].lower()
    assert str(source) not in result.output


def test_legacy_backup_help_is_unchanged() -> None:
    result = runner.invoke(app, ["backup", "--help"])
    assert result.exit_code == 0
    assert "legacy data-tree backup" in result.output
    assert "ssot" not in result.output
