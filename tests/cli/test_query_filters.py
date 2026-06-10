"""CLI tests for `query` with declarative report_filters."""

from __future__ import annotations

import json
from pathlib import Path

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import runner

COUNT_SQL = "WITH scoped AS (SELECT * FROM transactions) SELECT COUNT(*) AS total_rows FROM scoped"


def test_query_json_wraps_transactions_view_with_report_filters(
    report_filters_data_dir: Path,
) -> None:
    """The default query path should filter the conventional `transactions` view."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "query",
            COUNT_SQL,
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "query"
    assert payload["_meta"]["filters_applied"] == 3
    assert payload["rows"] == [{"total_rows": 1}]


def test_query_no_filter_flag_restores_unfiltered_transactions_view(
    report_filters_data_dir: Path,
) -> None:
    """`--no-filter` should bypass the query CTE wrapper and expose all rows."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "--no-filter",
            "query",
            COUNT_SQL,
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["rows"] == [{"total_rows": 3}]
