"""Tests for the finjuice skill runtime ensure helper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills/finjuice/scripts/ensure_finjuice_cli.sh"
INSTALL_COMMAND = "uv tool install git+https://github.com/sungjunlee/finjuice"
UPDATE_COMMAND = "uv tool install --force git+https://github.com/sungjunlee/finjuice"
FALLBACK_COMMAND = "uvx --from git+https://github.com/sungjunlee/finjuice finjuice --help"
UV_TOOL_INSTALL_ARGS = "tool install git+https://github.com/sungjunlee/finjuice"
UV_TOOL_UPDATE_ARGS = "tool install --force git+https://github.com/sungjunlee/finjuice"
UPDATE_COMMAND_JSON = f"{SCRIPT_PATH} --update --json"
DEFAULT_NOW = "1777939200"
ANALYTICS_INSTALL_COMMAND = (
    "uv tool install --with duckdb git+https://github.com/sungjunlee/finjuice"
)
ANALYTICS_UPDATE_COMMAND = (
    "uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice"
)
ANALYTICS_UV_TOOL_INSTALL_ARGS = (
    "tool install --with duckdb git+https://github.com/sungjunlee/finjuice"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_script(
    tmp_path: Path,
    bin_dir: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert SCRIPT_PATH.exists(), f"Missing runtime ensure helper: {SCRIPT_PATH}"
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }
    if env_extra is not None:
        env.update(env_extra)
    return subprocess.run(
        [str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _runtime_state_path(tmp_path: Path) -> Path:
    return tmp_path / "home/.finjuice/agent-runtime-state.json"


def test_existing_finjuice_json_reports_ready_without_uv_install(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 9.9.9"
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{uv_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 9.9.9",
        "runtime": "path",
        "update_check_status": "disabled",
        "update_available": False,
        "update_check_message": "remote runtime update check skipped for this run",
    }
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == ["--version"]
    assert not uv_calls.exists()


def test_existing_finjuice_without_version_option_reports_ready_if_help_works(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  exit 2
fi
if [ "$1" = "--help" ]; then
  printf '%s\\n' "Usage: finjuice [OPTIONS] COMMAND [ARGS]..."
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{uv_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice unknown (--version unsupported)",
        "runtime": "path",
        "update_check_status": "disabled",
        "update_available": False,
        "update_check_message": "remote runtime update check skipped for this run",
    }
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == ["--version", "--help"]
    assert not uv_calls.exists()


def test_update_flag_runs_forced_uv_install_then_rechecks_version_json(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf 'old %s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 9.9.9"
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
if [ "$*" != "{UV_TOOL_UPDATE_ARGS}" ]; then
  exit 64
fi
cat > "{bin_dir / "finjuice"}" <<'FINJUICE'
#!/usr/bin/env bash
printf 'updated %s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 10.0.0"
  exit 0
fi
exit 64
FINJUICE
chmod +x "{bin_dir / "finjuice"}"
""",
    )

    result = _run_script(tmp_path, bin_dir, "--update", "--json")

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "updated",
        "finjuice_version": "finjuice 10.0.0",
        "runtime": "uv-tool",
        "update_requested": True,
    }
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [UPDATE_COMMAND]
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == ["updated --version"]


def test_auto_update_env_runs_same_forced_uv_install(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 8.8.8"
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
if [ "$*" != "{UV_TOOL_UPDATE_ARGS}" ]; then
  exit 64
fi
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_AUTO_UPDATE": "1"},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "updated",
        "finjuice_version": "finjuice 8.8.8",
        "runtime": "uv-tool",
        "update_requested": True,
    }
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [UPDATE_COMMAND]


def test_existing_finjuice_plain_text_reports_ready(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 8.0.0"
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert "finjuice ready" in result.stdout
    assert "version: finjuice 8.0.0" in result.stdout
    assert "install: none" in result.stdout
    assert "runtime: path" in result.stdout
    assert "update_check: disabled" in result.stdout


def test_existing_finjuice_stale_ttl_checks_remote_once_and_reports_newer_json(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    curl_calls = tmp_path / "curl.calls"
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{curl_calls}"
printf '%s\\n' '[{{"name":"v1.2.0"}}]'
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{uv_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": DEFAULT_NOW},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 1.0.0",
        "runtime": "path",
        "update_check_status": "checked",
        "update_available": True,
        "remote_version": "1.2.0",
        "update_command": UPDATE_COMMAND_JSON,
    }
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == ["--version"]
    assert len(curl_calls.read_text(encoding="utf-8").splitlines()) == 1
    assert not uv_calls.exists()

    state = json.loads(_runtime_state_path(tmp_path).read_text(encoding="utf-8"))
    assert state["last_update_check_at"] == int(DEFAULT_NOW)
    assert state["last_seen_local_version"] == "1.0.0"
    assert state["last_seen_remote_version"] == "1.2.0"
    assert state["last_update_check_status"] == "checked"
    assert state["snoozed_until"] is None


def test_existing_finjuice_fresh_ttl_skips_remote_and_uses_cached_newer_json(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_path = _runtime_state_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "last_update_check_at": int(DEFAULT_NOW),
                "last_update_check_at_iso": "2026-05-05T00:00:00Z",
                "last_seen_local_version": "1.0.0",
                "last_seen_remote_version": "1.2.0",
                "last_update_check_status": "checked",
                "snoozed_until": None,
                "snoozed_until_iso": "",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    curl_calls = tmp_path / "curl.calls"
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{curl_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": str(int(DEFAULT_NOW) + 3600)},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 1.0.0",
        "runtime": "path",
        "update_check_status": "fresh",
        "update_available": True,
        "remote_version": "1.2.0",
        "update_command": UPDATE_COMMAND_JSON,
    }
    assert not curl_calls.exists()


def test_existing_finjuice_stale_ttl_same_remote_has_no_update_suggestion(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_path = _runtime_state_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "last_update_check_at": int(DEFAULT_NOW) - 90000,
                "last_update_check_at_iso": "2026-05-03T23:00:00Z",
                "last_seen_local_version": "1.0.0",
                "last_seen_remote_version": "1.0.0",
                "last_update_check_status": "checked",
                "snoozed_until": None,
                "snoozed_until_iso": "",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    curl_calls = tmp_path / "curl.calls"
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{curl_calls}"
printf '%s\\n' '[{{"name":"v1.0.0"}}]'
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": DEFAULT_NOW},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 1.0.0",
        "runtime": "path",
        "update_check_status": "checked",
        "update_available": False,
        "remote_version": "1.0.0",
    }
    assert len(curl_calls.read_text(encoding="utf-8").splitlines()) == 1


def test_remote_check_failure_is_nonfatal_with_existing_finjuice(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    curl_calls = tmp_path / "curl.calls"
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{curl_calls}"
exit 7
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": DEFAULT_NOW},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 1.0.0",
        "runtime": "path",
        "update_check_status": "failed",
        "update_available": False,
        "update_check_message": (
            "remote runtime update check failed; continuing with local finjuice"
        ),
    }
    assert len(curl_calls.read_text(encoding="utf-8").splitlines()) == 1
    state = json.loads(_runtime_state_path(tmp_path).read_text(encoding="utf-8"))
    assert state["last_update_check_at"] == int(DEFAULT_NOW)
    assert state["last_update_check_status"] == "failed"


def test_malformed_remote_metadata_is_nonfatal_with_existing_finjuice(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '%s\\n' '{"unexpected":true}'
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": DEFAULT_NOW},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 1.0.0",
        "runtime": "path",
        "update_check_status": "malformed",
        "update_available": False,
        "update_check_message": (
            "remote runtime metadata did not include a parseable version; continuing with "
            "local finjuice"
        ),
    }


def test_snooze_update_check_is_bounded_and_skips_remote(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    curl_calls = tmp_path / "curl.calls"
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{curl_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--snooze-update-check",
        "99",
        env_extra={"FINJUICE_RUNTIME_NOW_EPOCH": DEFAULT_NOW},
    )

    snoozed_until = int(DEFAULT_NOW) + (30 * 86400)
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "ready"
    assert payload["update_check_status"] == "snoozed"
    assert payload["update_available"] is False
    assert payload["snoozed_until"] == snoozed_until
    assert not curl_calls.exists()

    state = json.loads(_runtime_state_path(tmp_path).read_text(encoding="utf-8"))
    assert state["snoozed_until"] == snoozed_until
    assert state["last_update_check_status"] == "snoozed"


def test_missing_finjuice_installs_with_uv_tool_then_rechecks_version_json(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
if [ "$*" != "{UV_TOOL_INSTALL_ARGS}" ]; then
  exit 64
fi
cat > "{bin_dir / "finjuice"}" <<'FINJUICE'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.2.3"
  exit 0
fi
exit 64
FINJUICE
chmod +x "{bin_dir / "finjuice"}"
""",
    )

    result = _run_script(tmp_path, bin_dir, "--json")

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "installed",
        "finjuice_version": "finjuice 1.2.3",
        "runtime": "uv-tool",
    }
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [INSTALL_COMMAND]


def test_missing_finjuice_and_uv_json_blocks_without_installing_uv(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    result = _run_script(tmp_path, bin_dir, "--json")

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "uv_missing",
        "message": (
            "finjuice CLI is not installed and uv is not available; install uv first, "
            "then rerun this helper."
        ),
        "install_action": "none",
        "runtime": "none",
        "fallback_example": FALLBACK_COMMAND,
    }


def test_missing_finjuice_and_uv_plain_text_includes_install_and_fallback(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    result = _run_script(tmp_path, bin_dir)

    assert result.returncode != 0
    assert "finjuice runtime ensure blocked" in result.stdout
    assert "reason: uv_missing" in result.stdout
    assert "install uv first" in result.stdout
    assert f"fallback: {FALLBACK_COMMAND}" in result.stdout


def test_uv_install_failure_plain_text_is_nonzero_and_clear(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
printf '%s\\n' "simulated uv install failure" >&2
exit 42
""",
    )

    result = _run_script(tmp_path, bin_dir)

    assert result.returncode != 0
    assert "finjuice runtime ensure blocked" in result.stdout
    assert "reason: install_failed" in result.stdout
    assert INSTALL_COMMAND in result.stdout
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [INSTALL_COMMAND]


def test_uv_install_failure_json_is_nonzero_and_parseable(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "uv",
        """#!/usr/bin/env bash
exit 42
""",
    )

    result = _run_script(tmp_path, bin_dir, "--json")

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "install_failed",
        "message": (
            "uv tool install git+https://github.com/sungjunlee/finjuice failed; "
            "finjuice was not installed."
        ),
        "install_action": "failed",
        "runtime": "uv-tool",
        "exit_code": 42,
    }


def test_update_failure_json_is_nonzero_with_update_failed_reason(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
exit 42
""",
    )

    result = _run_script(tmp_path, bin_dir, "--json", "--update")

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "update_failed",
        "message": (
            "uv tool install --force git+https://github.com/sungjunlee/finjuice failed; "
            "finjuice was not updated."
        ),
        "install_action": "failed",
        "runtime": "uv-tool",
        "exit_code": 42,
        "update_requested": True,
    }
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [UPDATE_COMMAND]


def test_update_failure_plain_text_is_nonzero_and_clear(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
printf '%s\\n' "simulated uv update failure" >&2
exit 43
""",
    )

    result = _run_script(tmp_path, bin_dir, "--update")

    assert result.returncode != 0
    assert "finjuice runtime ensure blocked" in result.stdout
    assert "reason: update_failed" in result.stdout
    assert UPDATE_COMMAND in result.stdout
    assert "install: failed" in result.stdout
    assert "runtime: uv-tool" in result.stdout
    assert "update_requested: true" in result.stdout
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [UPDATE_COMMAND]


def test_update_missing_uv_blocks_without_using_existing_finjuice(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.0.0"
  exit 0
fi
exit 64
""",
    )

    result = _run_script(tmp_path, bin_dir, "--json", "--update")

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "update_failed",
        "message": (
            "finjuice update was requested, but uv is not available; install uv first, "
            "then rerun the helper with --update."
        ),
        "install_action": "failed",
        "runtime": "none",
        "update_requested": True,
    }
    assert not finjuice_calls.exists()


def test_required_capability_json_reports_local_and_required_runtime(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.2"
  exit 0
fi
if [ "$1" = "tag" ] && [ "$2" = "--help" ]; then
  printf '%s\\n' "Options: --edit"
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--require-version",
        "0.6.2",
        "--require-capability",
        "tag.edit",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 0.6.2",
        "runtime": "path",
        "required_version": "0.6.2",
        "required_capabilities": ["tag.edit"],
        "capability_checks": [
            {
                "capability": "tag.edit",
                "status": "pass",
                "cli_path": "finjuice tag --edit",
                "check": "finjuice tag --help contains --edit",
            }
        ],
        "update_check_status": "disabled",
        "update_available": False,
        "update_check_message": "remote runtime update check skipped for this run",
    }
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == [
        "--version",
        "tag --help",
    ]


def test_required_version_json_blocks_stale_runtime_without_update(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.1"
  exit 0
fi
exit 64
""",
    )
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{uv_calls}"
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--require-version",
        "0.6.2",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "version_unsupported",
        "message": (
            "finjuice 0.6.1 does not satisfy required finjuice version 0.6.2; "
            "explicitly update the runtime before using this skill."
        ),
        "install_action": "none",
        "runtime": "path",
        "finjuice_version": "finjuice 0.6.1",
        "local_version": "0.6.1",
        "required_version": "0.6.2",
        "update_command": UPDATE_COMMAND_JSON,
    }
    assert not uv_calls.exists()


def test_unsupported_required_capability_uses_standard_fallback_json(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.2"
  exit 0
fi
if [ "$1" = "tag" ] && [ "$2" = "--help" ]; then
  printf '%s\\n' "Options: --dry-run --json"
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--require-version",
        "0.6.2",
        "--require-capability",
        "tag.edit",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "blocked",
        "reason": "capability_unsupported",
        "message": (
            "Unsupported CLI path: finjuice tag --edit. Confidence lost for this "
            "workflow because the local finjuice runtime lacks required capability "
            "tag.edit. Do not recommend or run the failed command after preflight "
            "failure."
        ),
        "install_action": "none",
        "runtime": "path",
        "finjuice_version": "finjuice 0.6.2",
        "required_version": "0.6.2",
        "required_capabilities": ["tag.edit"],
        "unsupported_cli_path": "finjuice tag --edit",
        "confidence_lost": True,
        "capability_checks": [
            {
                "capability": "tag.edit",
                "status": "fail",
                "cli_path": "finjuice tag --edit",
                "check": "finjuice tag --help contains --edit",
            }
        ],
        "update_command": UPDATE_COMMAND_JSON,
    }
    assert "recommended_command" not in payload


def test_required_runtime_plain_text_includes_requirements(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.2"
  exit 0
fi
if [ "$1" = "tag" ] && [ "$2" = "--help" ]; then
  printf '%s\\n' "Options: --edit --json"
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--require-version",
        "0.6.2",
        "--require-capability",
        "tag.edit",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert "required_version: 0.6.2" in result.stdout
    assert "required_capabilities: tag.edit" in result.stdout
    assert "capability tag.edit: pass" in result.stdout


def test_required_analytics_extra_json_checks_duckdb_via_doctor(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    finjuice_calls = tmp_path / "finjuice.calls"
    _write_executable(
        bin_dir / "finjuice",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{finjuice_calls}"
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.2"
  exit 0
fi
if [ "$1" = "doctor" ] && [ "$2" = "--json" ]; then
  printf '%s\\n' '{{"checks":[{{"name":"analytics_duckdb","status":"pass"}}]}}'
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--require-extra",
        "analytics",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "ready",
        "install_action": "none",
        "finjuice_version": "finjuice 0.6.2",
        "runtime": "path",
        "required_imports": ["duckdb"],
        "import_checks": [
            {
                "module": "duckdb",
                "status": "pass",
                "cli_path": "finjuice doctor --json",
                "check": "finjuice doctor --json reports analytics_duckdb pass",
            }
        ],
        "required_extras": ["analytics"],
        "update_check_status": "disabled",
        "update_available": False,
        "update_check_message": "remote runtime update check skipped for this run",
    }
    assert finjuice_calls.read_text(encoding="utf-8").splitlines() == [
        "--version",
        "doctor --json",
    ]


def test_required_analytics_extra_missing_duckdb_blocks_with_recovery_command(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "finjuice",
        """#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 0.6.2"
  exit 0
fi
if [ "$1" = "doctor" ] && [ "$2" = "--json" ]; then
  printf '%s\\n' '{"checks":[{"name":"analytics_duckdb","status":"fail"}]}'
  exit 0
fi
exit 64
""",
    )

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        "--require-extra",
        "analytics",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "runtime_import_missing"
    assert payload["install_action"] == "none"
    assert payload["runtime"] == "path"
    assert payload["unsupported_import"] == "duckdb"
    assert payload["confidence_lost"] is True
    assert payload["required_imports"] == ["duckdb"]
    assert payload["required_extras"] == ["analytics"]
    assert payload["import_checks"] == [
        {
            "module": "duckdb",
            "status": "fail",
            "cli_path": "finjuice doctor --json",
            "check": "finjuice doctor --json reports analytics_duckdb pass",
        }
    ]
    assert payload["recovery_command"] == ANALYTICS_UPDATE_COMMAND


def test_missing_finjuice_installs_analytics_extra_with_duckdb_when_required(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_calls = tmp_path / "uv.calls"
    _write_executable(
        bin_dir / "uv",
        f"""#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "{uv_calls}"
if [ "$*" != "{ANALYTICS_UV_TOOL_INSTALL_ARGS}" ]; then
  exit 64
fi
cat > "{bin_dir / "finjuice"}" <<'FINJUICE'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
  printf '%s\\n' "finjuice 1.2.3"
  exit 0
fi
if [ "$1" = "doctor" ] && [ "$2" = "--json" ]; then
  printf '%s\\n' '{{"checks":[{{"name":"analytics_duckdb","status":"pass"}}]}}'
  exit 0
fi
exit 64
FINJUICE
chmod +x "{bin_dir / "finjuice"}"
""",
    )

    result = _run_script(tmp_path, bin_dir, "--json", "--require-extra", "analytics")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["install_action"] == "installed"
    assert payload["runtime"] == "uv-tool"
    assert payload["required_imports"] == ["duckdb"]
    assert uv_calls.read_text(encoding="utf-8").splitlines() == [ANALYTICS_INSTALL_COMMAND]


def test_broken_finjuice_symlink_blocks_with_runtime_path_and_recovery(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runtime_path = bin_dir / "finjuice"
    missing_target = tmp_path / "missing" / "finjuice"
    runtime_path.symlink_to(missing_target)

    result = _run_script(
        tmp_path,
        bin_dir,
        "--json",
        env_extra={"FINJUICE_RUNTIME_UPDATE_CHECK": "0"},
    )

    assert result.returncode != 0
    assert json.loads(result.stdout) == {
        "status": "blocked",
        "reason": "runtime_path_broken",
        "message": (
            "finjuice exists on PATH but its executable path is broken; update or force "
            "reinstall the uv tool runtime before using this skill."
        ),
        "install_action": "none",
        "runtime": "path",
        "runtime_path": str(runtime_path),
        "symlink_target": str(missing_target),
        "confidence_lost": True,
        "update_command": UPDATE_COMMAND_JSON,
        "recovery_command": UPDATE_COMMAND,
    }
