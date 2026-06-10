"""Tests for the dynamic `finjuice template run pivot` template."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.fixture
def pivot_data_dir(tmp_path: Path) -> Path:
    """Create a multi-month dataset for pivot-template coverage."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    df = pl.DataFrame(
        {
            "date": [
                "2024-10-01",
                "2024-10-02",
                "2024-10-03",
                "2024-11-05",
                "2024-12-10",
                "2025-01-12",
                "2025-01-15",
                "2025-02-20",
                "2025-02-22",
                "2025-02-25",
            ],
            "time": [
                "08:10",
                "19:45",
                "13:10",
                "09:00",
                "07:45",
                "14:00",
                "18:30",
                "09:05",
                "17:20",
                "22:10",
            ],
            "merchant_raw": [
                "Starbucks",
                "Netflix",
                "Coupang",
                "Salary",
                "Gym",
                "Transfer Out",
                "Pharmacy",
                "Bakery",
                "Bookstore",
                "Taxi",
            ],
            "amount": [
                -5000,
                -15000,
                -320000,
                200000,
                -45000,
                -100000,
                -23000,
                -12000,
                -30000,
                -40000,
            ],
            "memo_raw": [
                "coffee",
                "subscription",
                "shopping",
                "salary",
                "fitness",
                "internal transfer",
                "medicine",
                "bread",
                "books",
                "cab",
            ],
            "major_raw": [
                "Food",
                "Living",
                "Shopping",
                "Income",
                "Health",
                "Transfer",
                "Health",
                "Food",
                "Shopping",
                "Transport",
            ],
            "minor_raw": [
                "Cafe",
                "Sub",
                "Online",
                "Salary",
                "Gym",
                "Internal",
                "Pharmacy",
                "Bakery",
                "Books",
                "Taxi",
            ],
            "type_norm": [
                "expense",
                "expense",
                "expense",
                "income",
                "expense",
                "expense",
                "expense",
                "expense",
                "expense",
                "expense",
            ],
            "is_transfer": [0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
            "tags_final": [
                json.dumps(["cafe", "daily"]),
                json.dumps(["subscription"]),
                json.dumps(["shopping"]),
                json.dumps(["salary"]),
                json.dumps(["health", "subscription"]),
                json.dumps(["transfer"]),
                json.dumps(["health"]),
                json.dumps(["cafe"]),
                json.dumps(["books"]),
                json.dumps(["transport"]),
            ],
            "category_final": [
                "Cafe",
                "Subscription",
                "Shopping",
                "Income",
                "Health",
                "Transfer",
                "Health",
                "Cafe",
                "Shopping",
                "Transport",
            ],
            "account": [
                "Card A",
                "Card A",
                "Card B",
                "Card A",
                "Card B",
                "Card A",
                "Card A",
                "Card C",
                "Card C",
                "Card C",
            ],
        }
    ).with_columns(pl.col("date").str.slice(0, 7).alias("_ym"))

    for ym_value in df.get_column("_ym").unique().sort().to_list():
        year, month = ym_value.split("-", 1)
        month_dir = data_dir / "transactions" / year / month
        month_dir.mkdir(parents=True)
        df.filter(pl.col("_ym") == ym_value).drop("_ym").write_csv(month_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text(
        """
version: 1
rules: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return data_dir


def _run_pivot_json(
    data_dir: Path,
    *,
    row: str,
    col: str,
    value: str = "amount",
    agg: str | None = None,
    months: str | None = None,
    top_n_cols: int | None = None,
    no_filter: bool = False,
):
    args = ["--data-dir", str(data_dir)]
    if no_filter:
        args.append("--no-filter")
    args.extend(
        [
            "template",
            "run",
            "pivot",
            "--param",
            f"row={row}",
            "--param",
            f"col={col}",
            "--param",
            f"value={value}",
        ]
    )
    if agg is not None:
        args.extend(["--param", f"agg={agg}"])
    if months is not None:
        args.extend(["--param", f"months={months}"])
    if top_n_cols is not None:
        args.extend(["--param", f"top_n_cols={top_n_cols}"])
    args.append("--json")
    result = runner.invoke(app, args)
    payload = json.loads(result.output)
    return result, payload


def test_template_list_json_includes_pivot(pivot_data_dir: Path) -> None:
    """`template list --json` should surface the pivot template registry entry."""
    result = runner.invoke(
        app,
        ["--data-dir", str(pivot_data_dir), "template", "list", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    pivot_entry = next(item for item in payload["templates"] if item["name"] == "pivot")
    assert pivot_entry["description"] == "Dynamic pivot by row axis, column axis, and metric"
    assert set(pivot_entry["params"]) == {"row", "col", "value", "agg", "months", "top_n_cols"}


def test_template_run_pivot_month_category_json(pivot_data_dir: Path) -> None:
    """Month x category pivot should zero-fill missing cells and expose ordered columns."""
    result, payload = _run_pivot_json(pivot_data_dir, row="month", col="category_final")

    assert result.exit_code == 0, result.output
    assert payload["_meta"]["command"] == "template run"
    assert payload["_meta"]["columns"] == [
        "Shopping",
        "Income",
        "Transfer",
        "Health",
        "Transport",
        "Cafe",
        "Subscription",
    ]
    assert payload["template_name"] == "pivot"
    assert payload["row_count"] == 5
    assert payload["rows"][0] == {
        "month": "2024-10",
        "Shopping": 320000,
        "Income": 0,
        "Transfer": 0,
        "Health": 0,
        "Transport": 0,
        "Cafe": 5000,
        "Subscription": 15000,
    }
    assert payload["rows"][-1] == {
        "month": "2025-02",
        "Shopping": 30000,
        "Income": 0,
        "Transfer": 0,
        "Health": 0,
        "Transport": 40000,
        "Cafe": 12000,
        "Subscription": 0,
    }


def test_template_run_pivot_month_merchant_top_n_other_bucket(pivot_data_dir: Path) -> None:
    """Month x merchant pivots should cap to top N columns plus `_other_`."""
    result, payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="merchant_raw",
        top_n_cols=5,
    )

    assert result.exit_code == 0, result.output
    assert payload["_meta"]["columns"] == [
        "Coupang",
        "Salary",
        "Transfer Out",
        "Gym",
        "Taxi",
        "_other_",
    ]
    assert len(payload["_meta"]["columns"]) == 6
    month_rows = {row["month"]: row for row in payload["rows"]}
    assert month_rows["2024-10"]["_other_"] == 20000
    assert month_rows["2025-02"]["_other_"] == 42000


def test_template_run_pivot_tags_final_unnests_before_aggregation(pivot_data_dir: Path) -> None:
    """`col=tags_final` should explode each tag before aggregating pivot cells."""
    result, payload = _run_pivot_json(pivot_data_dir, row="month", col="tags_final")

    assert result.exit_code == 0, result.output
    month_rows = {row["month"]: row for row in payload["rows"]}
    assert month_rows["2024-10"]["cafe"] == 5000
    assert month_rows["2024-10"]["daily"] == 5000
    assert month_rows["2024-10"]["subscription"] == 15000
    assert month_rows["2024-12"]["health"] == 45000
    assert month_rows["2024-12"]["subscription"] == 45000


def test_template_run_pivot_quarter_category(pivot_data_dir: Path) -> None:
    """Quarter x category pivots should use DuckDB date bucketing, not string slicing."""
    result, payload = _run_pivot_json(pivot_data_dir, row="quarter", col="category_final")

    assert result.exit_code == 0, result.output
    quarter_rows = {row["quarter"]: row for row in payload["rows"]}
    assert quarter_rows["2024-Q4"]["Shopping"] == 320000
    assert quarter_rows["2024-Q4"]["Income"] == 200000
    assert quarter_rows["2024-Q4"]["Health"] == 45000
    assert quarter_rows["2025-Q1"]["Transfer"] == 100000
    assert quarter_rows["2025-Q1"]["Transport"] == 40000


def test_template_run_pivot_account_type_norm(pivot_data_dir: Path) -> None:
    """Account x type_norm pivots should support `type_norm` as a column axis."""
    result, payload = _run_pivot_json(pivot_data_dir, row="account", col="type_norm")

    assert result.exit_code == 0, result.output
    assert payload["_meta"]["columns"] == ["expense", "income"]
    account_rows = {row["account"]: row for row in payload["rows"]}
    assert account_rows["Card A"] == {"account": "Card A", "expense": 143000, "income": 200000}
    assert account_rows["Card B"] == {"account": "Card B", "expense": 365000, "income": 0}
    assert account_rows["Card C"] == {"account": "Card C", "expense": 82000, "income": 0}


def test_template_run_pivot_value_count_defaults_to_row_counts(pivot_data_dir: Path) -> None:
    """`value=count` should resolve the default aggregate into transaction counts."""
    result, payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="category_final",
        value="count",
    )

    assert result.exit_code == 0, result.output
    month_rows = {row["month"]: row for row in payload["rows"]}
    assert month_rows["2024-10"]["Shopping"] == 1
    assert month_rows["2024-10"]["Cafe"] == 1
    assert month_rows["2024-10"]["Subscription"] == 1
    assert month_rows["2025-02"]["Shopping"] == 1
    assert month_rows["2025-02"]["Transport"] == 1
    assert month_rows["2025-02"]["Cafe"] == 1


@pytest.mark.parametrize(
    ("top_n_cols", "expected_count", "has_other"),
    [
        (10, 10, False),
        (9, 10, True),
        (5, 6, True),
    ],
)
def test_template_run_pivot_top_n_cols_boundaries(
    pivot_data_dir: Path,
    top_n_cols: int,
    expected_count: int,
    has_other: bool,
) -> None:
    """`top_n_cols` should only add `_other_` when raw cardinality exceeds N."""
    result, payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="merchant_raw",
        top_n_cols=top_n_cols,
    )

    assert result.exit_code == 0, result.output
    assert len(payload["_meta"]["columns"]) == expected_count
    assert ("_other_" in payload["_meta"]["columns"]) is has_other


def test_template_run_pivot_months_filter_inclusive_and_empty_window(
    pivot_data_dir: Path,
) -> None:
    """Month-range filters should include both endpoints and return empty rows when unmatched."""
    in_range_result, in_range_payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="category_final",
        months="2024-10:2024-12",
    )
    empty_result, empty_payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="category_final",
        months="2023-01:2023-02",
    )

    assert in_range_result.exit_code == 0, in_range_result.output
    assert [row["month"] for row in in_range_payload["rows"]] == ["2024-10", "2024-11", "2024-12"]

    assert empty_result.exit_code == 0, empty_result.output
    assert empty_payload["_meta"]["columns"] == []
    assert empty_payload["rows"] == []


def test_template_run_pivot_rejects_reversed_month_range(pivot_data_dir: Path) -> None:
    """Reversed month ranges should fail fast with a helpful validation message."""
    result, payload = _run_pivot_json(
        pivot_data_dir,
        row="month",
        col="category_final",
        months="2025-02:2024-10",
    )

    assert result.exit_code == 3
    assert payload["_meta"]["command"] == "template run"
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "start month must be <= end month" in payload["error"]["message"]


@pytest.mark.parametrize(
    ("param_name", "param_value", "expected_message"),
    [
        (
            "row",
            "weekday",
            "Allowed: month, year, quarter, account, type_norm, is_transfer",
        ),
        (
            "col",
            "account",
            "Allowed: category_final, major_raw, minor_raw, merchant_raw, tags_final, type_norm",
        ),
        (
            "months",
            "2024-10/2024-12",
            "expected YYYY-MM:YYYY-MM",
        ),
    ],
)
def test_template_run_pivot_validation_errors(
    pivot_data_dir: Path,
    param_name: str,
    param_value: str,
    expected_message: str,
) -> None:
    """Invalid pivot params should surface content-rich validation errors."""
    args = [
        "--data-dir",
        str(pivot_data_dir),
        "template",
        "run",
        "pivot",
        "--param",
        "row=month",
        "--param",
        "col=category_final",
        "--json",
    ]
    args.extend(["--param", f"{param_name}={param_value}"])

    result = runner.invoke(app, args)

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert expected_message in payload["error"]["message"]


def test_template_run_pivot_report_filters_on_off(report_filters_data_dir: Path) -> None:
    """Pivot should honor shared report_filters and the root `--no-filter` override."""
    filtered_result, filtered_payload = _run_pivot_json(
        report_filters_data_dir,
        row="month",
        col="category_final",
    )
    unfiltered_result, unfiltered_payload = _run_pivot_json(
        report_filters_data_dir,
        row="month",
        col="category_final",
        no_filter=True,
    )

    assert filtered_result.exit_code == 0, filtered_result.output
    assert filtered_payload["_meta"]["filters_applied"] == 3
    assert filtered_payload["_meta"]["columns"] == ["식비"]
    assert filtered_payload["rows"] == [{"month": "2024-10", "식비": 50000.0}]

    assert unfiltered_result.exit_code == 0, unfiltered_result.output
    assert unfiltered_payload["_meta"]["filters_applied"] == 0
    assert unfiltered_payload["_meta"]["columns"] == ["생활", "의료", "식비"]
    assert unfiltered_payload["rows"] == [
        {"month": "2024-10", "생활": 300000.0, "의료": 100000.0, "식비": 50000.0}
    ]
