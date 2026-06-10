"""CLI tests for `export` with declarative report_filters."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import runner


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 BOM CSV report."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_xlsx_keeps_master_unfiltered_and_filters_reports(
    report_filters_data_dir: Path,
) -> None:
    """`export` should keep master.xlsx unfiltered while filtering report outputs."""
    result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "export", "--format", "xlsx", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "export"
    assert payload["_meta"]["filters_applied"] == 3
    assert payload["transaction_count"] == 3

    output_files = {item["kind"]: item for item in payload["output_files"]}
    assert output_files["master_xlsx"]["row_count"] == 3
    assert output_files["monthly_spend_report"]["row_count"] == 1

    report_rows = _read_csv_rows(
        report_filters_data_dir / "exports" / "reports" / "monthly_spend.csv"
    )
    assert len(report_rows) == 1
    assert report_rows[0]["month"] == "2024-10"
    assert float(report_rows[0]["total_spend"]) == -50000.0
    assert len(list((report_filters_data_dir / "exports").glob("master_*.xlsx"))) == 1


def test_export_dry_run_json_reports_filter_meta(report_filters_data_dir: Path) -> None:
    """`export --dry-run --json` should still report matched filter rule count."""
    result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "export", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["filters_applied"] == 3
