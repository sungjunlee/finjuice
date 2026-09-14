"""Actual CLI coverage for local snapshots and caller-bound inactive workspaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import sqlite_backup
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.backup import create_backup
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    RestoredWorkspaceReceipt,
)
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.pipeline.test_sqlite_backup import _build_generation

runner = CliRunner()


def _invoke(active: Path, *args: str):
    return runner.invoke(app, ["--data-dir", str(active), "ssot", "backup", *args])


def _validate(payload: dict, action: str) -> None:
    _validate_command_schema(
        payload, command=f"ssot backup {action}", schema_file=f"ssot_backup_{action}.schema.json"
    )


@pytest.mark.parametrize("machine", [True, False])
def test_actual_snapshot_restore_and_status(tmp_path: Path, machine: bool) -> None:
    source = _build_generation(tmp_path / "source")
    backup = tmp_path / "backup"
    workspace = tmp_path / "restored"
    flags = ["--json"] if machine else []
    for action, args in (
        ("create", ["--source", str(source.database), "--output", str(backup)]),
        ("status", [str(backup)]),
        ("restore", [str(backup), "--target", str(workspace)]),
    ):
        result = _invoke(tmp_path / "active", action, *args, *flags)
        assert result.exit_code == 0, result.output
        assert str(tmp_path) not in result.output
        if machine:
            payload = json.loads(result.output)
            _validate(payload, action)
        else:
            assert "SQLite" in result.output
    assert (backup / "backup-current.json").is_file()
    assert (workspace / "generation" / "finjuice.sqlite3").is_file()
    assert (workspace / "restore-control" / "descriptor.json").is_file()
    if not machine:
        from tests.conftest import cli_text

        payload, _ = json.JSONDecoder().raw_decode("{" + cli_text(result).split("{", 1)[1])
    receipt = RestoredWorkspaceReceipt(
        workspace=workspace, **{key: value for key, value in payload.items() if key != "_meta"}
    )
    with InactiveRestoreSession(receipt) as session:
        session.backup(tmp_path / "rebackup")


@pytest.mark.parametrize("case", ["same", "child", "parent", "dotdot", "active_alias"])
def test_restore_rejects_active_overlap_without_effects(tmp_path: Path, case: str) -> None:
    source = _build_generation(tmp_path / "source")
    create_backup(source.database, tmp_path / "backup")
    active = tmp_path / "active"
    target = active
    if case == "child":
        target = active / "child"
    elif case == "parent":
        active = active / "child"
    elif case == "dotdot":
        active = tmp_path / "other" / ".." / "active"
    elif case == "active_alias":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        active = alias / "active"
    result = _invoke(active, "restore", str(tmp_path / "backup"), "--target", str(target), "--json")
    assert result.exit_code != 0
    assert not target.exists()
    assert str(tmp_path) not in result.output
    assert json.loads(result.output)["error"]


@pytest.mark.parametrize("case", ["dangling", "ancestor", "dotdot"])
def test_restore_rejects_unsafe_target(tmp_path: Path, case: str) -> None:
    source = _build_generation(tmp_path / "source")
    create_backup(source.database, tmp_path / "backup")
    target = tmp_path / "target"
    if case == "dangling":
        target.symlink_to(tmp_path / "missing")
    elif case == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        target = alias / "target"
    else:
        target = tmp_path / "unused" / ".." / "target"
    result = _invoke(
        tmp_path / "active", "restore", str(tmp_path / "backup"), "--target", str(target), "--json"
    )
    assert result.exit_code != 0
    assert not (tmp_path / "target" / "generation").exists()
    assert str(tmp_path) not in result.output


@pytest.mark.parametrize("machine", [True, False])
def test_invalid_config_cannot_bypass_restore_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, machine: bool
) -> None:
    source = _build_generation(tmp_path / "source")
    create_backup(source.database, tmp_path / "backup")

    def invalid_config():
        raise ValueError(f"PRIVATE_CONFIGURATION {tmp_path}")

    monkeypatch.setattr(sqlite_backup, "load_config", invalid_config)
    flags = ["--json"] if machine else []
    result = _invoke(
        tmp_path / "active",
        "restore",
        str(tmp_path / "backup"),
        "--target",
        str(tmp_path / "target"),
        *flags,
    )
    assert result.exit_code != 0
    assert "PRIVATE_CONFIGURATION" not in result.output
    assert str(tmp_path) not in result.output
    assert not (tmp_path / "target").exists()


def test_tampered_snapshot_status_and_restore(tmp_path: Path) -> None:
    source = _build_generation(tmp_path / "source")
    backup = tmp_path / "backup"
    created = create_backup(source.database, backup)
    (created.manifest_path.parent / "finjuice.sqlite3").write_bytes(b"PRIVATE_CORRUPT")
    result = _invoke(tmp_path / "active", "status", str(backup), "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    _validate(payload, "status")
    assert payload["complete"] is False
    result = _invoke(
        tmp_path / "active", "restore", str(backup), "--target", str(tmp_path / "target"), "--json"
    )
    assert result.exit_code != 0
    assert "PRIVATE_CORRUPT" not in result.output
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("machine", [True, False])
def test_malformed_config_is_static_before_root_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, machine: bool
) -> None:
    from finjuice.pipeline import config_file

    config_path = tmp_path / "PRIVATE_CONFIG.toml"
    config_path.write_text("[PRIVATE_MALFORMED")
    monkeypatch.setattr(config_file, "get_config_path", lambda: config_path)
    flags = ["--json"] if machine else []
    result = _invoke(
        tmp_path / "active",
        "restore",
        str(tmp_path / "backup"),
        "--target",
        str(tmp_path / "target"),
        *flags,
    )
    assert result.exit_code != 0
    assert "PRIVATE" not in result.output
    assert str(tmp_path) not in result.output
    assert not (tmp_path / "target").exists()


def test_manifest_backup_policy() -> None:
    result = runner.invoke(app, ["manifest", "--json"])
    assert result.exit_code == 0
    commands = {item["path"]: item for item in json.loads(result.output)["commands"]}
    for action in ("create", "restore", "status"):
        policy = commands[f"ssot backup {action}"]
        assert policy["mutates_data"] is (action != "status")
        assert policy["safe_readonly"] is (action == "status")
        assert policy["privacy_profile"] == "artifact_path"


@pytest.mark.parametrize(
    ("arguments", "resolved"),
    [
        (
            ["--data-dir", "backup", "--verbose", "ssot", "backup", "status", "missing", "--json"],
            False,
        ),
        (["--verbose", "--data-dir", "ssot", "ssot", "migrate", "--help"], True),
        (["--data-dir", "ssot", "backup", "--help"], True),
    ],
)
def test_only_parsed_sqlite_backup_subtree_defers_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str], resolved: bool
) -> None:
    import importlib

    main_module = importlib.import_module("finjuice.pipeline.cli.main")
    observed = []

    def resolve(data_dir):
        observed.append(data_dir)
        return tmp_path / "active"

    monkeypatch.setattr(main_module, "_resolve_active_data_dir", resolve)
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert bool(observed) is resolved
