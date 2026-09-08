"""CLI tests for backup create/verify/restore JSON and human output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.mark.parametrize("json_output", [True, False])
@pytest.mark.parametrize("operation", ["create", "restore"])
def test_unsupported_platform_error_is_safe_in_both_output_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool, operation: str
) -> None:
    from finjuice.pipeline.backup import publish as backup_publish

    source = _source_tree(tmp_path)
    output = tmp_path / "output"
    args = _create_args(source, output)
    if operation == "restore":
        output.mkdir()
        args = [
            "--data-dir",
            str(source),
            "backup",
            "restore",
            str(tmp_path / "unused-manifest"),
            "--target",
            str(output),
            "--json",
        ]
    if not json_output:
        args.remove("--json")
    monkeypatch.setattr(backup_publish.sys, "platform", "win32")

    result = runner.invoke(app, args)

    assert result.exit_code != 0
    message = json.loads(result.output)["error"]["message"] if json_output else result.output
    assert "require Linux or macOS" in message
    assert str(source) not in result.output
    assert str(output) not in result.output
    assert not list(tmp_path.glob(".finjuice-backup-staging-*"))
    if operation == "restore":
        assert list(output.iterdir()) == []
    else:
        assert not output.exists()


def _source_tree(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "transactions" / "2024" / "01").mkdir(parents=True)
    (source / "transactions" / "2024" / "01" / "transactions.csv").write_text(
        "a,b\n1,2\n", encoding="utf-8"
    )
    (source / "empty_dir").mkdir()
    (source / "rules.yaml").write_text("version: 1\n", encoding="utf-8")
    return source


def _create_args(source: Path, output: Path) -> list[str]:
    return [
        "backup",
        "create",
        "--source",
        str(source),
        "--output",
        str(output),
        "--consistency",
        "stopped-writers",
        "--stopped-writer",
        "cli",
        "--optional-root",
        "image_cache",
        "--json",
    ]


def test_backup_json_success_has_no_source_paths(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "backup"
    result = runner.invoke(app, _create_args(source, output))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "backup create"
    assert payload["status"] == "ok"
    blob = result.output
    assert str(source) not in blob
    assert "transactions.csv" not in blob
    assert "rules.yaml" not in blob
    assert str(output) not in blob


def test_invalid_source_schema_evidence_is_private_and_non_blocking(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    schema_file = source / "metadata" / "schema_version"
    schema_file.parent.mkdir()
    schema_file.write_text("private-invalid-value\n", encoding="utf-8")
    output = tmp_path / "backup"

    result = runner.invoke(app, _create_args(source, output))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data_schema_version"] is None
    assert payload["data_schema_version_status"] == "invalid"
    assert "private-invalid-value" not in result.output
    assert str(schema_file) not in result.output


def test_backup_verify_restore_json_envelope(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "backup"
    created = runner.invoke(app, _create_args(source, output))
    assert created.exit_code == 0, created.output
    manifest = output / "backup-manifest.json"
    verified = runner.invoke(app, ["backup", "verify", str(manifest), "--json"])
    assert verified.exit_code == 0, verified.output
    verify_payload = json.loads(verified.output)
    assert verify_payload["_meta"]["command"] == "backup verify"
    assert verify_payload["status"] == "ok"

    target = tmp_path / "restored"
    restored = runner.invoke(
        app,
        ["backup", "restore", str(manifest), "--target", str(target), "--json"],
    )
    assert restored.exit_code == 0, restored.output
    restore_payload = json.loads(restored.output)
    assert restore_payload["_meta"]["command"] == "backup restore"
    assert restore_payload["generation_status"] == "inactive"
    assert str(source) not in restored.output
    assert "rules.yaml" not in restored.output


def test_backup_human_and_json_failures_hide_paths(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    result = runner.invoke(
        app,
        [
            "backup",
            "create",
            "--source",
            str(source),
            "--output",
            str(source / "inside"),
            "--consistency",
            "stopped-writers",
            "--stopped-writer",
            "cli",
            "--json",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"]["code"] in {"INVALID_ARGS", "VALIDATION_FAILED"}
    assert str(source) not in result.output
    assert "inside" not in result.output.lower() or "overlap" in payload["error"]["message"].lower()
    assert "transactions.csv" not in result.output

    human = runner.invoke(
        app,
        [
            "backup",
            "create",
            "--source",
            str(source),
            "--output",
            str(source / "inside"),
            "--consistency",
            "stopped-writers",
            "--stopped-writer",
            "cli",
        ],
    )
    assert human.exit_code != 0
    assert str(source) not in human.output
    assert "Traceback" not in human.output


def test_backup_create_and_verify_skip_invalid_active_data_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINJUICE_DATA_DIR", str(tmp_path / "missing-active"))
    source = _source_tree(tmp_path)
    output = tmp_path / "backup"
    result = runner.invoke(app, _create_args(source, output))
    assert result.exit_code == 0, result.output
    verified = runner.invoke(app, ["backup", "verify", str(output), "--json"])
    assert verified.exit_code == 0, verified.output


def test_backup_restore_fails_closed_on_invalid_active_data_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "backup"
    created = runner.invoke(app, _create_args(source, output))
    assert created.exit_code == 0, created.output
    monkeypatch.setenv("FINJUICE_DATA_DIR", str(tmp_path / "missing" / "active"))
    from finjuice.pipeline.cli.commands import backup as backup_cli

    def fail_config(**_kwargs: object) -> None:
        raise OSError

    monkeypatch.setattr(backup_cli.Config, "from_env", fail_config)
    result = runner.invoke(
        app,
        ["backup", "restore", str(output), "--target", str(tmp_path / "restored"), "--json"],
    )

    assert result.exit_code != 0
    assert "active data directory" in json.loads(result.output)["error"]["message"].lower()
    assert not (tmp_path / "restored").exists()


def test_required_root_missing_cli(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    result = runner.invoke(
        app,
        [
            *_create_args(source, tmp_path / "backup"),
            "--source-root",
            f"journal={tmp_path / 'missing-journal'}",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert "missing" in payload["error"]["message"].lower()
    assert "missing-journal" not in result.output
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("json_output", [True, False])
def test_duplicate_cli_root_names_fail_without_omitting_a_source(
    tmp_path: Path, json_output: bool
) -> None:
    source = _source_tree(tmp_path)
    first, second = tmp_path / "first.yaml", tmp_path / "second.yaml"
    first.write_text("first: true\n")
    second.write_text("second: true\n")
    output = tmp_path / "backup"
    args = _create_args(source, output)
    if not json_output:
        args.remove("--json")

    result = runner.invoke(
        app,
        [*args, "--source-root", f"overlay={first}", "--source-root", f"overlay={second}"],
    )

    assert result.exit_code != 0
    if json_output:
        assert "duplicate" in json.loads(result.output)["error"]["message"].lower()
    assert str(first) not in result.output
    assert str(second) not in result.output
    assert not output.exists()
    assert first.read_text() == "first: true\n"
    assert second.read_text() == "second: true\n"
