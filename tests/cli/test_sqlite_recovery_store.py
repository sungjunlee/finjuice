"""Operator CLI for the initialized local recovery-graph store."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.recovery_store import (
    capture_into_store,
    initialize_recovery_store,
)
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.cli.test_sqlite_recovery_bundle import _write_expected
from tests.pipeline.test_recovery_bundle import _live

runner = CliRunner()


def _invoke(active: Path, *args: str):
    return runner.invoke(app, ["--data-dir", str(active), "ssot", "backup", "store", *args])


def _store_args(store: Path, expected_path: Path, source) -> list[str]:
    paths = source.release_paths
    return [
        "--store",
        str(store),
        "--source-data-dir",
        str(source.data_dir),
        "--expected",
        str(expected_path),
        "--wheel",
        str(paths.wheel),
        "--dependency-lock",
        str(paths.dependency_lock),
        "--binding",
        str(paths.binding),
        "--migration-candidate",
        str(source.migration_candidate),
    ]


def test_store_cli_human_and_json_round_trip(tmp_path: Path) -> None:
    source, expected, paths, _generation, _transactions, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    store = tmp_path / "store"
    active = tmp_path / "active"
    initialized = _invoke(
        active, "init", "--store", str(store), "--expected", str(expected_path), "--json"
    )
    assert initialized.exit_code == 0, initialized.output
    payload = json.loads(initialized.output)
    _validate_command_schema(
        payload,
        command="ssot backup store init",
        schema_file="ssot_backup_store_init.schema.json",
    )
    captured = _invoke(active, "capture", *_store_args(store, expected_path, source), "--json")
    assert captured.exit_code == 0, captured.output
    capture_payload = json.loads(captured.output)
    _validate_command_schema(
        capture_payload,
        command="ssot backup store capture",
        schema_file="ssot_backup_store_capture.schema.json",
    )
    copy_id = capture_payload["copy_id"]
    listed = _invoke(
        active, "list", "--store", str(store), "--expected", str(expected_path), "--json"
    )
    assert listed.exit_code == 0, listed.output
    _validate_command_schema(
        json.loads(listed.output),
        command="ssot backup store list",
        schema_file="ssot_backup_store_list.schema.json",
    )
    verified = _invoke(
        active,
        "verify",
        "--store",
        str(store),
        "--copy-id",
        copy_id,
        "--expected",
        str(expected_path),
        "--json",
    )
    assert verified.exit_code == 0, verified.output
    human = _invoke(active, "plan", "--store", str(store), "--expected", str(expected_path))
    assert human.exit_code == 0, human.output
    assert "Local recovery store retention plan" in human.output
    restored = _invoke(
        active,
        "restore",
        "--store",
        str(store),
        "--copy-id",
        copy_id,
        "--target",
        str(tmp_path / "workspace"),
        "--expected",
        str(expected_path),
        "--json",
    )
    assert restored.exit_code == 0, restored.output
    restore_payload = json.loads(restored.output)
    _validate_command_schema(
        restore_payload,
        command="ssot backup store restore",
        schema_file="ssot_backup_store_restore.schema.json",
    )
    assert restore_payload["dataset_generation"]
    assert str(tmp_path) not in restored.output
    assert paths.activation.is_file()


def test_store_cli_rejects_expected_mismatch_and_active_restore_target(tmp_path: Path) -> None:
    source, expected, _paths, _generation, _transactions, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    other = json.loads(expected_path.read_text(encoding="utf-8"))
    other["activation_sha256"] = "b" * 64
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps(other), encoding="utf-8")
    store = tmp_path / "store"
    initialize_recovery_store(store, expected)
    captured = capture_into_store(store, source, expected)
    active = source.data_dir
    mismatched = _invoke(
        tmp_path / "cli-active",
        "list",
        "--store",
        str(store),
        "--expected",
        str(mismatch),
        "--json",
    )
    assert mismatched.exit_code != 0, mismatched.output
    payload = json.loads(mismatched.output)
    assert "copy_id" not in payload
    blocked = _invoke(
        active,
        "restore",
        "--store",
        str(store),
        "--copy-id",
        captured.copy_id,
        "--target",
        str(active),
        "--expected",
        str(expected_path),
        "--json",
    )
    assert blocked.exit_code != 0, blocked.output
    assert (store / "bundles" / captured.copy_id / "recovery-graph.json").is_file()
    assert not (active / "restore-control").exists()
