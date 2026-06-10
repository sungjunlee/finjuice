"""CLI tests for `show` with declarative report_filters."""

from __future__ import annotations

import json
from pathlib import Path

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import runner


def test_show_json_excludes_report_filtered_rows(report_filters_data_dir: Path) -> None:
    """`show --json` should hide rows excluded by report_filters."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "show",
            "--month",
            "2024-10",
            "--limit",
            "10",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "show"
    assert payload["_meta"]["filters_applied"] == 3
    assert payload["total_matches"] == 1
    assert [row["merchant_raw"] for row in payload["rows"]] == ["마트"]
