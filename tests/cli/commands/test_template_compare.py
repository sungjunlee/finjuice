"""CLI tests for the compare SQL template."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_transactions import write_month
from tests.cli.report_filter_support import build_cli_data_dir as _build_cli_data_dir

runner = CliRunner()


def compare_row(
    *,
    row_hash: str,
    date: str,
    merchant: str,
    amount: float,
    category: str,
    major: str,
    account: str = "Test Card",
    is_transfer: int = 0,
) -> dict[str, object]:
    """Build a minimal transaction row for compare template tests."""
    return {
        "row_hash": row_hash,
        "date": date,
        "time": "09:00",
        "datetime": f"{date}T09:00:00",
        "type_raw": "지출" if amount < 0 else "수입",
        "type_norm": "expense" if amount < 0 else "income",
        "merchant_raw": merchant,
        "amount": amount,
        "memo_raw": "",
        "major_raw": major,
        "minor_raw": category,
        "account": account,
        "category_final": category,
        "tags_final": ["compare"],
        "is_transfer": is_transfer,
    }


@pytest.fixture
def compare_data_dir(tmp_path: Path) -> Path:
    """Create a multi-month dataset for compare template scenarios."""
    data_dir = _build_cli_data_dir(
        tmp_path,
        """
        version: 1
        rules: []
        """,
    )

    rows = [
        compare_row(
            row_hash="2024-01-groceries",
            date="2024-01-05",
            merchant="Mart",
            amount=-100000.0,
            category="Groceries",
            major="Food",
        ),
        compare_row(
            row_hash="2024-01-coffee",
            date="2024-01-07",
            merchant="Starbucks",
            amount=-5000.0,
            category="Coffee",
            major="Food",
        ),
        compare_row(
            row_hash="2024-01-salary",
            date="2024-01-25",
            merchant="Employer",
            amount=3000000.0,
            category="Salary",
            major="Income",
            account="Payroll",
        ),
        compare_row(
            row_hash="2024-02-groceries",
            date="2024-02-10",
            merchant="Mart",
            amount=-120000.0,
            category="Groceries",
            major="Food",
        ),
        compare_row(
            row_hash="2024-02-electronics",
            date="2024-02-12",
            merchant="TechStore",
            amount=-200000.0,
            category="Electronics",
            major="Shopping",
        ),
        compare_row(
            row_hash="2024-02-salary",
            date="2024-02-25",
            merchant="Employer",
            amount=3100000.0,
            category="Salary",
            major="Income",
            account="Payroll",
        ),
        compare_row(
            row_hash="2024-03-groceries",
            date="2024-03-10",
            merchant="Mart",
            amount=-110000.0,
            category="Groceries",
            major="Food",
        ),
        compare_row(
            row_hash="2024-03-coffee",
            date="2024-03-11",
            merchant="Starbucks",
            amount=-6000.0,
            category="Coffee",
            major="Food",
        ),
        compare_row(
            row_hash="2024-03-travel",
            date="2024-03-15",
            merchant="Air",
            amount=-400000.0,
            category="Travel",
            major="Leisure",
        ),
        compare_row(
            row_hash="2024-03-salary",
            date="2024-03-25",
            merchant="Employer",
            amount=3200000.0,
            category="Salary",
            major="Income",
            account="Payroll",
        ),
        compare_row(
            row_hash="2024-04-groceries",
            date="2024-04-10",
            merchant="Mart",
            amount=-130000.0,
            category="Groceries",
            major="Food",
        ),
        compare_row(
            row_hash="2024-04-coffee",
            date="2024-04-11",
            merchant="Starbucks",
            amount=-7000.0,
            category="Coffee",
            major="Food",
        ),
        compare_row(
            row_hash="2024-04-travel",
            date="2024-04-20",
            merchant="Air",
            amount=-100000.0,
            category="Travel",
            major="Leisure",
        ),
        compare_row(
            row_hash="2024-04-salary",
            date="2024-04-25",
            merchant="Employer",
            amount=3300000.0,
            category="Salary",
            major="Income",
            account="Payroll",
        ),
        compare_row(
            row_hash="2024-05-groceries",
            date="2024-05-10",
            merchant="Mart",
            amount=-90000.0,
            category="Groceries",
            major="Food",
        ),
        compare_row(
            row_hash="2024-05-dining",
            date="2024-05-18",
            merchant="Bistro",
            amount=-50000.0,
            category="Dining",
            major="Food",
        ),
    ]

    df = pl.DataFrame(rows).with_columns(pl.col("date").str.slice(0, 7).alias("_ym"))
    for ym_value in sorted(df["_ym"].unique().to_list()):
        year, month = ym_value.split("-")
        month_rows = df.filter(pl.col("_ym") == ym_value).drop("_ym")
        write_month(data_dir / "transactions", month_rows, int(year), int(month))

    return data_dir


def test_template_list_json_includes_compare(compare_data_dir: Path) -> None:
    """Template registry JSON should include the compare template."""
    result = runner.invoke(
        app,
        ["--data-dir", str(compare_data_dir), "template", "list", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    compare = next(item for item in payload["templates"] if item["name"] == "compare")
    assert compare["description"].startswith("Baseline-vs-current")
    assert set(compare["params"]) == {"baseline_months", "current_months", "group_by", "type_norm"}


def test_template_run_compare_range_months_orders_by_absolute_diff(compare_data_dir: Path) -> None:
    """Range-form compare should include one-sided groups and sort by absolute diff."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-01:2024-02",
            "--param",
            "current_months=2024-03:2024-04",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template run"
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["_meta"]["baseline_months_count"] == 2
    assert payload["_meta"]["current_months_count"] == 2
    assert payload["template_name"] == "compare"
    assert payload["row_count"] == 4

    rows = payload["rows"]
    assert [row["group_key"] for row in rows] == ["Travel", "Electronics", "Groceries", "Coffee"]

    travel = rows[0]
    assert travel["baseline_monthly_avg"] == 0.0
    assert travel["current_monthly_avg"] == 250000.0
    assert travel["diff"] == 250000.0
    assert travel["pct_change"] is None

    electronics = rows[1]
    assert electronics["baseline_monthly_avg"] == 100000.0
    assert electronics["current_monthly_avg"] == 0.0
    assert electronics["diff"] == -100000.0
    assert electronics["pct_change"] == -100.0


def test_template_run_compare_list_months_supports_group_by(
    compare_data_dir: Path,
) -> None:
    """List-form months should work with merchant grouping and parsed month counts."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-01,2024-02,2024-03",
            "--param",
            "current_months=2024-04,2024-05,2024-06",
            "--param",
            "group_by=merchant_raw",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["baseline_months_count"] == 3
    assert payload["_meta"]["current_months_count"] == 3
    assert payload["row_count"] == 5

    mart = next(row for row in payload["rows"] if row["group_key"] == "Mart")
    assert mart["baseline_monthly_avg"] == 110000.0
    assert mart["current_monthly_avg"] == 110000.0
    assert mart["diff"] == 0.0

    techstore = next(row for row in payload["rows"] if row["group_key"] == "TechStore")
    assert techstore["baseline_monthly_avg"] == 66666.7
    assert techstore["current_monthly_avg"] == 0.0


def test_template_run_compare_empty_baseline_keeps_current_rows(
    compare_data_dir: Path,
) -> None:
    """Missing baseline months should keep current rows and null out pct_change."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2023-12",
            "--param",
            "current_months=2024-03:2024-04",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["row_count"] == 3
    assert all(row["baseline_monthly_avg"] == 0.0 for row in payload["rows"])
    assert all(row["pct_change"] is None for row in payload["rows"])

    travel = next(row for row in payload["rows"] if row["group_key"] == "Travel")
    assert travel["current_monthly_avg"] == 250000.0
    assert travel["diff"] == 250000.0


def test_template_run_compare_bad_month_window_shows_format_hint(
    compare_data_dir: Path,
) -> None:
    """Invalid month input should surface the accepted formats."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-1:2024-02",
            "--param",
            "current_months=2024-03:2024-04",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "baseline_months" in payload["error"]["message"]
    assert "YYYY-MM:YYYY-MM or YYYY-MM,YYYY-MM,..." in payload["error"]["message"]


def test_template_run_compare_reverse_range_fails_helpfully(compare_data_dir: Path) -> None:
    """Reverse month ranges should be rejected before SQL execution."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-04:2024-03",
            "--param",
            "current_months=2024-03:2024-04",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert "baseline_months" in payload["error"]["message"]
    assert "start month must be <= end month" in payload["error"]["message"]


def test_template_run_compare_rejects_invalid_group_by(compare_data_dir: Path) -> None:
    """group_by should fail fast with the enum allowlist."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(compare_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-01:2024-02",
            "--param",
            "current_months=2024-03:2024-04",
            "--param",
            "group_by=minor_raw",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert "group_by" in payload["error"]["message"]
    assert "category_final, major_raw, merchant_raw" in payload["error"]["message"]


def test_template_run_compare_respects_report_filters(
    report_filters_data_dir: Path,
) -> None:
    """Compare should reuse the shared report_filters application path."""
    filtered_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-10",
            "--param",
            "current_months=2024-10",
            "--output",
            "json",
        ],
    )
    no_filter_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "--no-filter",
            "template",
            "run",
            "compare",
            "--param",
            "baseline_months=2024-10",
            "--param",
            "current_months=2024-10",
            "--output",
            "json",
        ],
    )

    assert filtered_result.exit_code == 0, filtered_result.output
    assert no_filter_result.exit_code == 0, no_filter_result.output

    filtered_payload = json.loads(filtered_result.output)
    no_filter_payload = json.loads(no_filter_result.output)

    assert filtered_payload["_meta"]["filters_applied"] == 3
    assert filtered_payload["row_count"] == 1
    assert filtered_payload["rows"][0]["group_key"] == "식비"
    assert filtered_payload["rows"][0]["baseline_monthly_avg"] == 50000.0

    assert no_filter_payload["_meta"]["filters_applied"] == 0
    assert no_filter_payload["row_count"] == 3
