"""Tests for installed CLI JSON smoke helper behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import smoke_installed_cli_json


def test_default_matrix_is_small_and_covers_representative_json_surfaces() -> None:
    """The default smoke matrix should stay broad enough without becoming exhaustive."""
    selected = smoke_installed_cli_json.select_commands(None)

    assert [command.name for command in selected] == [
        "status",
        "doctor",
        "manifest",
        "rules-list",
        "rules-suggest",
        "query",
        "explain",
        "template-run",
        "networth-forecast",
        "checkup-compact",
    ]


def test_select_commands_filters_matrix_in_declared_order() -> None:
    """The smoke command filter should support focused debugging runs."""
    selected = smoke_installed_cli_json.select_commands("query,status")

    assert [command.name for command in selected] == ["status", "query"]


def test_select_commands_rejects_unknown_names() -> None:
    """Typos in --commands should fail before building and installing artifacts."""
    with pytest.raises(smoke_installed_cli_json.CliJsonSmokeError, match="unknown"):
        smoke_installed_cli_json.select_commands("status,missing-command")


def test_format_failure_includes_category_artifact_command_and_stderr() -> None:
    """Smoke failures should distinguish package/install issues from JSON drift."""
    message = smoke_installed_cli_json.format_failure(
        category="schema-drift",
        artifact=Path("/tmp/finjuice-1.2.3-py3-none-any.whl"),
        command=("finjuice", "status", "--json"),
        detail="$.transactions.count: 'one' is not of type 'integer'",
        output=smoke_installed_cli_json.CapturedOutput(stderr="validator stderr\nsecond line"),
    )

    assert "[schema-drift]" in message
    assert "finjuice-1.2.3-py3-none-any.whl" in message
    assert "finjuice status --json" in message
    assert "validator stderr\nsecond line" in message
    assert "$.transactions.count" in message


def test_install_wheel_environment_uses_host_jsonschema_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Schema validation runs in the parent process, not inside the target smoke venv."""
    wheel_path = tmp_path / "dist" / "finjuice-1.2.3-py3-none-any.whl"
    wheel_path.parent.mkdir()
    wheel_path.write_text("placeholder", encoding="utf-8")

    def fake_create_stdlib_venv(venv_dir: Path) -> Path:
        return venv_dir / "bin" / "python"

    def fake_isolated_runtime_env(*, venv_dir: Path, runtime_root: Path) -> dict[str, str]:
        del venv_dir, runtime_root
        return {"PATH": "smoke"}

    def fake_install_artifact(
        *,
        python_path: Path,
        artifact_path: Path,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        del python_path, cwd, env
        assert artifact_path == wheel_path

    def fail_run_command(*args: object, **kwargs: object) -> object:
        del args, kwargs
        pytest.fail("install_wheel_environment must not probe or install jsonschema")

    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "create_stdlib_venv",
        fake_create_stdlib_venv,
    )
    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "isolated_runtime_env",
        fake_isolated_runtime_env,
    )
    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "install_artifact",
        fake_install_artifact,
    )
    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "run_command",
        fail_run_command,
    )

    runtime = smoke_installed_cli_json.install_wheel_environment(
        wheel_path=wheel_path,
        temp_root=tmp_path,
    )

    assert runtime.artifact == wheel_path
    assert runtime.env == {"PATH": "smoke"}
    assert (runtime.data_dir / "rules.yaml").read_text(encoding="utf-8").count(
        "smoke_merchant"
    ) == 1
    assert (runtime.data_dir / "assets.yaml").is_file()
    assert (runtime.data_dir / "scenarios.yaml").is_file()


def test_install_wheel_environment_installs_analytics_extra_only_when_needed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Query/explain smoke commands need the package analytics extra, not jsonschema."""
    wheel_path = tmp_path / "dist" / "finjuice-1.2.3-py3-none-any.whl"
    wheel_path.parent.mkdir()
    wheel_path.write_text("placeholder", encoding="utf-8")
    install_commands: list[tuple[str, ...]] = []

    def fake_create_stdlib_venv(venv_dir: Path) -> Path:
        return venv_dir / "bin" / "python"

    def fake_isolated_runtime_env(*, venv_dir: Path, runtime_root: Path) -> dict[str, str]:
        del venv_dir, runtime_root
        return {"PATH": "smoke"}

    def fake_run_command(
        args: list[str | Path],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, timeout
        install_commands.append(tuple(str(arg) for arg in args))
        return subprocess.CompletedProcess(args=[str(arg) for arg in args], returncode=0)

    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "create_stdlib_venv",
        fake_create_stdlib_venv,
    )
    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "isolated_runtime_env",
        fake_isolated_runtime_env,
    )
    monkeypatch.setattr(
        smoke_installed_cli_json.smoke_installed_artifact,
        "run_command",
        fake_run_command,
    )

    smoke_installed_cli_json.install_wheel_environment(
        wheel_path=wheel_path,
        temp_root=tmp_path,
        include_analytics_extra=True,
    )

    assert len(install_commands) == 1
    assert install_commands[0][1:4] == ("-m", "pip", "install")
    assert install_commands[0][4].startswith("finjuice[analytics] @ file://")
    assert all("jsonschema" not in part for command in install_commands for part in command)
