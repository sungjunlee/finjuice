"""CLI tests for the root-level `--no-filter` flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import runner


@pytest.mark.parametrize(
    ("args", "assertion"),
    [
        (
            ["status", "--json"],
            lambda payload: payload["transactions"]["count"] == 3,
        ),
        (
            ["template", "run", "monthly_spend", "--json"],
            lambda payload: payload["rows"][0]["total_spend"] == 450000.0,
        ),
        (
            ["show", "--month", "2024-10", "--json", "--limit", "10"],
            lambda payload: payload["total_matches"] == 3,
        ),
        (
            ["export", "--dry-run", "--json"],
            lambda payload: payload["command"] == "export",
        ),
        (
            ["query", "SELECT COUNT(*) AS total_rows FROM transactions", "--output", "json"],
            lambda payload: payload["rows"] == [{"total_rows": 3}],
        ),
    ],
)
def test_no_filter_flag_disables_report_filters_across_commands(
    report_filters_data_dir: Path,
    args: list[str],
    assertion,
) -> None:
    """The root-level flag should zero out filter application for all supported commands."""
    result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "--no-filter", *args],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["filters_applied"] == 0
    assert assertion(payload)
