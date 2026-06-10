"""CLI tests for JSON output support in audit commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from tests.conftest import cli_text

runner = CliRunner()


def _write_audit_log(data_dir: Path, events: list[dict[str, object]]) -> Path:
    """Write audit events to the standard JSONL audit log file."""
    audit_log_path = data_dir / ".execution_audit.jsonl"
    with open(audit_log_path, "w", encoding="utf-8") as audit_log:
        for event in events:
            audit_log.write(json.dumps(event) + "\n")
    return audit_log_path


@pytest.fixture
def audit_json_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with sample audit events for JSON output tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    events: list[dict[str, object]] = [
        {
            "timestamp": "2024-10-01T10:00:00",
            "event": "command_suggested",
            "command": "finjuice tag",
            "user_confirmed": True,
        },
        {
            "timestamp": "2024-10-01T10:01:00",
            "event": "command_executed",
            "command": "finjuice tag",
            "success": True,
            "duration": 1.2,
            "returncode": 0,
        },
        {
            "timestamp": "2024-10-01T10:02:00",
            "event": "command_suggested",
            "command": "finjuice tag",
            "user_confirmed": True,
        },
        {
            "timestamp": "2024-10-01T10:03:00",
            "event": "command_suggested",
            "command": "finjuice export",
            "user_confirmed": False,
        },
        {
            "timestamp": "2024-10-01T10:04:00",
            "event": "command_executed",
            "command": "finjuice export",
            "success": False,
            "duration": 2.5,
            "returncode": 1,
        },
    ]
    _write_audit_log(data_dir, events)

    return data_dir


@pytest.fixture
def audit_json_large_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with more than 100 audit events for clear tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    events = [
        {
            "timestamp": f"2024-10-{(index // 24) + 1:02d}T{index % 24:02d}:00:00",
            "event": "command_suggested",
            "command": f"finjuice cmd_{index}",
            "user_confirmed": index % 2 == 0,
        }
        for index in range(120)
    ]
    _write_audit_log(data_dir, events)

    return data_dir


@pytest.fixture
def empty_audit_data_dir(tmp_path: Path) -> Path:
    """Create a data directory without an audit log file."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def audit_json_template_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with template_run events for template summary tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    events: list[dict[str, object]] = [
        {
            "timestamp": "2024-10-01T10:00:00",
            "event": "template_run",
            "command": "finjuice ask --report asset_top_holdings",
            "template_name": "asset_top_holdings",
            "template_domain": "asset",
            "success": False,
            "duration": 0.2,
            "output_format": "markdown",
            "param_keys": [],
            "param_fingerprint": "asset:none",
            "error_type": "TyperExit",
        },
        {
            "timestamp": "2024-10-01T10:00:02",
            "event": "template_run",
            "command": "finjuice ask --report asset_top_holdings",
            "template_name": "asset_top_holdings",
            "template_domain": "asset",
            "success": True,
            "duration": 0.4,
            "output_format": "markdown",
            "param_keys": [],
            "param_fingerprint": "asset:none",
        },
        {
            "timestamp": "2024-10-01T10:00:05",
            "event": "template_run",
            "command": "finjuice template run monthly_spend",
            "template_name": "monthly_spend",
            "template_domain": "transaction",
            "success": True,
            "duration": 0.6,
            "output_format": "json",
            "param_keys": ["since"],
            "param_fingerprint": "monthly:2024-10",
        },
    ]
    _write_audit_log(data_dir, events)

    return data_dir


def test_audit_log_json_returns_events_with_meta(audit_json_data_dir: Path) -> None:
    """`audit log --json` should return an events array wrapped with `_meta`."""
    # Arrange
    command = ["--data-dir", str(audit_json_data_dir), "audit", "log", "--json"]

    # Act
    result = runner.invoke(app, command)

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "audit log"
    assert payload["count"] == 5
    assert len(payload["events"]) == 5
    assert payload["events"][0]["event"] == "command_suggested"
    assert payload["events"][1]["command"] == "finjuice tag"


def test_audit_stats_json_returns_summary_with_meta(audit_json_data_dir: Path) -> None:
    """`audit stats --json` should return a structured summary wrapped with `_meta`."""
    # Arrange
    command = ["--data-dir", str(audit_json_data_dir), "audit", "stats", "--json"]

    # Act
    result = runner.invoke(app, command)

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "audit stats"
    assert payload["suggestions"] == {"total": 3, "confirmed": 2, "declined": 1}
    assert payload["executions"] == {"total": 2, "successful": 1, "failed": 1}
    assert payload["success_rate"] == 50.0
    assert payload["top_commands"][0] == {"command": "finjuice tag", "count": 2}
    assert payload["skipped_entries"] == 0


def test_audit_stats_json_includes_template_summary(
    audit_json_template_data_dir: Path,
) -> None:
    """`audit stats --json` should expose template metrics when template_run events exist."""
    command = ["--data-dir", str(audit_json_template_data_dir), "audit", "stats", "--json"]

    result = runner.invoke(app, command)

    assert result.exit_code == 0, result.output
    payload = json.loads(cli_text(result))
    template_summary = payload["template_summary"]

    assert payload["_meta"]["command"] == "audit stats"
    assert payload["skipped_entries"] == 0
    assert template_summary["overall"]["total"] == 3
    assert template_summary["overall"]["retry_attempts"] == 1
    assert template_summary["overall"]["retry_recovery"] == pytest.approx(100.0)
    assert template_summary["asset"]["failed"] == 1
    assert template_summary["transaction"]["success"] == 1
    assert template_summary["usage_counts"]["asset_top_holdings"] == 2
    assert template_summary["domain_usage_counts"]["transaction"]["monthly_spend"] == 1


def test_audit_clear_json_returns_result_with_meta(audit_json_large_data_dir: Path) -> None:
    """`audit clear --json --yes` should emit a structured clear result."""
    # Arrange
    audit_log_path = audit_json_large_data_dir / ".execution_audit.jsonl"
    command = ["--data-dir", str(audit_json_large_data_dir), "audit", "clear", "--yes", "--json"]

    # Act
    result = runner.invoke(app, command)

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "audit clear"
    assert payload["entries_kept"] == 100
    assert payload["action"] == "cleared"
    assert payload["skipped_entries"] == 0
    assert len(audit_log_path.read_text(encoding="utf-8").splitlines()) == 100


def test_audit_clear_json_cancelled_returns_error_payload(audit_json_large_data_dir: Path) -> None:
    """`audit clear --json` should keep JSON output when the confirmation is declined."""
    audit_log_path = audit_json_large_data_dir / ".execution_audit.jsonl"
    original_lines = audit_log_path.read_text(encoding="utf-8").splitlines()
    command = ["--data-dir", str(audit_json_large_data_dir), "audit", "clear", "--json"]

    result = runner.invoke(app, command, input="n\n")

    assert result.exit_code == ExitCode.USER_CANCELLED, result.output
    assert "Clear audit log (keep last 100 entries)?" not in result.stdout
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["_meta"]["command"] == "audit clear"
    assert payload["error"]["code"] == ErrorCode.USER_CANCELLED
    assert payload["error"]["message"] == "Audit log clear cancelled by user."
    assert payload["exit_code"] == ExitCode.USER_CANCELLED
    assert "Clear audit log (keep last 100 entries)?" in result.stderr
    assert audit_log_path.read_text(encoding="utf-8").splitlines() == original_lines


@pytest.mark.parametrize(
    ("args", "expected_fields"),
    [
        (["audit", "log", "--json"], {"count": 1}),
        (
            ["audit", "stats", "--json"],
            {"suggestions": {"total": 1, "confirmed": 1, "declined": 0}},
        ),
        (["audit", "clear", "--yes", "--json"], {"entries_kept": 1, "action": "cleared"}),
    ],
)
def test_audit_json_success_payloads_include_skipped_entries(
    tmp_path: Path,
    args: list[str],
    expected_fields: dict[str, object],
) -> None:
    """Successful JSON responses should report malformed rows that were skipped."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    audit_log_path = data_dir / ".execution_audit.jsonl"
    valid_event = {
        "timestamp": "2024-10-01T10:00:00",
        "event": "command_suggested",
        "command": "finjuice tag",
        "user_confirmed": True,
    }
    audit_log_path.write_text(json.dumps(valid_event) + "\ninvalid json\n", encoding="utf-8")

    result = runner.invoke(app, ["--data-dir", str(data_dir), *args])

    assert result.exit_code == 0, result.output
    payload = json.loads(cli_text(result))
    assert payload["skipped_entries"] == 1
    for key, value in expected_fields.items():
        assert payload[key] == value


@pytest.mark.parametrize(
    ("args", "expected_text"),
    [
        (["audit", "log"], "Audit Log"),
        (["audit", "stats"], "Statistics"),
    ],
)
def test_audit_commands_without_json_preserve_rich_output(
    audit_json_data_dir: Path,
    args: list[str],
    expected_text: str,
) -> None:
    """Commands should keep Rich text rendering when `--json` is not set."""
    # Arrange
    command = ["--data-dir", str(audit_json_data_dir), *args]

    # Act
    result = runner.invoke(app, command)

    # Assert
    assert result.exit_code == 0, result.output
    output = cli_text(result)
    assert expected_text in output
    assert '"_meta"' not in output


@pytest.mark.parametrize(
    ("args", "expected_command"),
    [
        (["audit", "log", "--json"], "audit log"),
        (["audit", "stats", "--json"], "audit stats"),
        (["audit", "clear", "--yes", "--json"], "audit clear"),
    ],
)
def test_audit_commands_with_missing_log_emit_json_errors(
    empty_audit_data_dir: Path,
    args: list[str],
    expected_command: str,
) -> None:
    """Missing audit logs should return JSON errors when `--json` is requested."""
    # Arrange
    command = ["--data-dir", str(empty_audit_data_dir), *args]

    # Act
    result = runner.invoke(app, command)

    # Assert
    assert result.exit_code == ExitCode.NO_DATA, result.output
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == expected_command
    assert payload["error"]["code"] == ErrorCode.NO_DATA
    assert "No audit log found" in payload["error"]["message"]
    assert payload["exit_code"] == ExitCode.NO_DATA
