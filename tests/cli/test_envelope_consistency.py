"""Regression tests for top-level JSON envelope consistency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()
pytest_plugins = ("tests.cli.test_json_output",)


@pytest.fixture
def envelope_data_dir(json_output_data_dir: Path) -> Path:
    """Extend the shared JSON fixture with audit events for audit log coverage."""
    audit_log = json_output_data_dir / ".execution_audit.jsonl"
    audit_log.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-04T00:00:00+00:00",
                "event": "command_executed",
                "command": "finjuice status",
                "success": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return json_output_data_dir


@pytest.mark.parametrize(
    ("label", "cmd_args"),
    [
        ("status", ["status", "--json"]),
        ("checkup", ["checkup", "--json"]),
        ("context", ["context", "--json"]),
        ("doctor", ["doctor", "--json"]),
        ("history", ["history", "--json"]),
        ("query", ["query", "SELECT 1 AS one", "--json"]),
        ("show", ["show", "--json"]),
        ("journal list", ["journal", "list", "--json"]),
        ("rules list", ["rules", "list", "--json"]),
        ("audit log", ["audit", "log", "--json"]),
        ("networth validate", ["networth", "validate", "--json"]),
    ],
)
def test_json_commands_include_required_meta(
    envelope_data_dir: Path,
    label: str,
    cmd_args: list[str],
) -> None:
    """Every structured stdout JSON command should include the standard _meta envelope."""
    result = runner.invoke(app, ["--data-dir", str(envelope_data_dir), *cmd_args])

    assert result.exit_code == 0, f"{label} failed: {result.output[:400]}"
    payload: Any = json.loads(result.output)
    assert isinstance(payload, dict), f"{label} returned {type(payload).__name__}, not object"

    missing = [
        key
        for key in ("schema_version", "finjuice_version", "command", "timestamp")
        if key not in payload.get("_meta", {})
    ]
    assert not missing, f"{label} missing _meta keys: {missing}"

    if label == "journal list":
        assert "entries" in payload
        assert payload["count"] == len(payload["entries"])
