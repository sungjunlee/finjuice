"""Tests for `finjuice budget` commands."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
import yaml
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.budget_period import (
    latest_budget_window,
    parse_budget_period,
    resolve_budget_period,
)
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode

runner = CliRunner()


@pytest.fixture
def budget_data_dir(tmp_path: Path) -> Path:
    """Create a multi-month dataset plus goals.yaml for budget testing."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  # keep this comment",
                "  total: 250000",
                "  categories:",
                "    식비: 100000",
                "    교통: 50000",
                "    카페: 30000",
                '  updated: "2026-04-15"',
                '  notes: "April review budget"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    march_rows = pl.DataFrame(
        [
            _transaction_row("2026-03-05", -30_000, "식비", "March Grocer"),
            _transaction_row("2026-03-06", -20_000, "교통", "March Bus"),
        ]
    )
    april_rows = pl.DataFrame(
        [
            _transaction_row("2026-04-02", -95_000, "식비", "April Grocer"),
            _transaction_row("2026-04-03", -20_000, "교통", "April Taxi"),
            _transaction_row("2026-04-04", -40_000, "카페", "April Cafe"),
            _transaction_row("2026-04-05", -15_000, "의료", "April Clinic"),
            _transaction_row(
                "2026-04-06",
                -10_000,
                "이체",
                "Internal Transfer",
                is_transfer=1,
                type_norm="transfer",
                type_raw="이체",
            ),
        ]
    )

    _write_month(data_dir, march_rows, "2026", "03")
    _write_month(data_dir, april_rows, "2026", "04")
    return data_dir


def test_budget_status_json_reports_total_category_states_and_unbudgeted_spend(
    budget_data_dir: Path,
) -> None:
    """Budget status should include total rollup, category states, and unbudgeted rows."""
    result = runner.invoke(
        app,
        ["--data-dir", str(budget_data_dir), "budget", "status", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    rows = {row["name"]: row for row in payload["categories"]}

    assert payload["_meta"]["command"] == "budget status"
    assert payload["_meta"]["month"] == "2026-04"
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["summary"] == {
        "name": "Total",
        "target": 250000,
        "actual": 170000,
        "remaining": 80000,
        "progress_pct": 68.0,
        "status": "under",
    }
    assert rows["식비"]["status"] == "on-track"
    assert rows["식비"]["progress_pct"] == 95.0
    assert rows["교통"]["status"] == "under"
    assert rows["카페"]["status"] == "over"
    assert rows["의료"] == {
        "name": "의료",
        "target": 0,
        "actual": 15000,
        "remaining": -15000,
        "progress_pct": None,
        "status": "over",
    }
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["over_budget_categories", "unbudgeted_spend"],
    }
    assert payload["actionable"] is True
    assert payload["signals"] == {
        "goals_file_exists": True,
        "over_budget_count": 1,
        "unbudgeted_count": 1,
        "on_track_count": 1,
        "under_budget_count": 1,
        "remaining_total": 80000,
        "filters_applied": 0,
    }
    assert payload["review"] == {
        "month": "2026-04",
        "target": 250000,
        "actual": 170000,
        "remaining": 80000,
        "at_risk_categories": ["식비", "카페", "의료"],
        "over_budget_categories": ["카페"],
        "unbudgeted_categories": ["의료"],
    }
    assert payload["next_steps"] == [
        {
            "signal": "over_budget_categories",
            "message": "Inspect this month's review queue before changing the budget.",
            "command": "finjuice review --json --month 2026-04",
        },
        {
            "signal": "budget_adjustment",
            "message": "Update goals.yaml targets when the current budget is outdated.",
            "command": "finjuice budget edit --help",
        },
    ]
    assert payload["unmatched_goal_categories"] == []


def test_budget_status_missing_goals_yaml_returns_empty_envelope(
    no_report_filters_data_dir: Path,
) -> None:
    """Missing goals.yaml should be a polite empty budget envelope."""
    result = runner.invoke(
        app,
        ["--data-dir", str(no_report_filters_data_dir), "budget", "status", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["_meta"]["command"] == "budget status"
    assert payload["goals_file"]["exists"] is False
    assert payload["summary"] is None
    assert payload["categories"] == []
    assert payload["health"] == {
        "status": "critical",
        "reasons": ["missing_goals_file"],
    }
    assert payload["actionable"] is True
    assert payload["signals"] == {
        "goals_file_exists": False,
        "over_budget_count": 0,
        "unbudgeted_count": 0,
        "on_track_count": 0,
        "under_budget_count": 0,
        "remaining_total": None,
        "filters_applied": 0,
    }
    assert payload["review"] == {
        "month": payload["month"],
        "target": None,
        "actual": None,
        "remaining": None,
        "at_risk_categories": [],
        "over_budget_categories": [],
        "unbudgeted_categories": [],
    }
    assert payload["next_steps"] == [
        {
            "signal": "missing_goals_file",
            "message": "Create monthly budget targets before relying on budget status.",
            "command": "finjuice budget edit --help",
        }
    ]
    assert payload["unmatched_goal_categories"] == []


def test_budget_status_missing_goals_yaml_preserves_filter_metadata(
    report_filters_data_dir: Path,
) -> None:
    """Missing goals.yaml should still surface the real report-filter count."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "budget",
            "status",
            "--json",
            "--month",
            "2024-10",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["_meta"]["month"] == "2024-10"
    assert payload["_meta"]["filters_applied"] == 3
    assert payload["goals_file"]["exists"] is False
    assert payload["summary"] is None
    assert payload["categories"] == []
    assert payload["signals"]["filters_applied"] == 3


def test_budget_status_unbudgeted_only_uses_matching_next_step_signal(tmp_path: Path) -> None:
    """Unbudgeted-only warnings should not emit an over-budget next-step signal."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 300000",
                "  categories:",
                "    식비: 200000",
                '  updated: "2026-04-15"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_month(
        data_dir,
        pl.DataFrame(
            [
                _transaction_row("2026-04-02", -80_000, "식비", "Grocer"),
                _transaction_row("2026-04-03", -20_000, "의료", "Clinic"),
            ]
        ),
        "2026",
        "04",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "status", "--json", "--month", "2026-04"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["unbudgeted_spend"],
    }
    assert payload["signals"]["over_budget_count"] == 0
    assert payload["signals"]["unbudgeted_count"] == 1
    assert payload["next_steps"][0]["signal"] == "unbudgeted_spend"


def test_budget_status_excludes_savings_from_total_and_unbudgeted(tmp_path: Path) -> None:
    """Savings-type expenses must not inflate Total.actual or unbudgeted rows."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 200000",
                "  categories:",
                "    식비: 100000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_month(
        data_dir,
        pl.DataFrame(
            [
                _transaction_row("2026-04-02", -80_000, "식비", "Grocer"),
                _transaction_row("2026-04-03", -50_000, "저축", "Monthly Savings"),
            ]
        ),
        "2026",
        "04",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "status", "--json", "--month", "2026-04"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    rows = {row["name"]: row for row in payload["categories"]}

    assert payload["summary"]["actual"] == 80_000
    assert "저축" not in rows
    assert payload["signals"]["unbudgeted_count"] == 0
    assert payload["review"]["unbudgeted_categories"] == []
    assert "non-consumption" in payload["_meta"]["inclusion"]
    assert "savings" in payload["_meta"]["inclusion"]

    help_result = runner.invoke(app, ["budget", "status", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "non-consumption" in help_result.output

    human_result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "status", "--month", "2026-04"],
    )
    assert human_result.exit_code == 0, human_result.output
    assert "non-consumption" in human_result.output


def test_budget_edit_round_trip_preserves_comments_and_skips_prompt_with_yes(
    budget_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`budget edit --yes` should not prompt and should preserve comments/other keys."""

    def _fail_confirm(*args: object, **kwargs: object) -> bool:
        raise AssertionError("typer.confirm should not be called when --yes is set")

    monkeypatch.setattr("finjuice.pipeline.cli.commands.budget.typer.confirm", _fail_confirm)

    goals_path = budget_data_dir / "goals.yaml"
    goals_path.write_text(
        "\n".join(
            [
                "version: 1",
                'owner: "solo-dev"',
                "monthly_budget:",
                "  # keep this comment",
                "  total: 250000",
                "  categories:",
                "    식비: 100000",
                "    교통: 50000",
                "    카페: 30000",
                '  updated: "2026-04-15"',
                '  notes: "April review budget"',
                "  rollover_strategy: carry-forward",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(budget_data_dir),
            "budget",
            "edit",
            "--set",
            "식비=700000",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    updated_text = goals_path.read_text(encoding="utf-8")
    updated_yaml = yaml.safe_load(updated_text)

    assert "# keep this comment" in updated_text
    assert updated_yaml["version"] == 1
    assert updated_yaml["owner"] == "solo-dev"
    assert updated_yaml["monthly_budget"]["total"] == 250000
    assert updated_yaml["monthly_budget"]["notes"] == "April review budget"
    assert updated_yaml["monthly_budget"]["rollover_strategy"] == "carry-forward"
    assert updated_yaml["monthly_budget"]["categories"]["식비"] == 700000

    status_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(budget_data_dir),
            "budget",
            "status",
            "--json",
            "--month",
            "2026-04",
        ],
    )
    status_payload = json.loads(status_result.output)
    rows = {row["name"]: row for row in status_payload["categories"]}
    assert rows["식비"]["target"] == 700000


def test_budget_validate_surfaces_line_numbered_schema_errors(tmp_path: Path) -> None:
    """Invalid goals.yaml should fail validation with line-numbered messages."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: -1",
                "  categories: {}",
                '  updated: "2026-02-30"',
                "  notes: 123",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "validate"],
    )

    assert result.exit_code == 3, result.output
    assert "Line 3, column 3: monthly_budget.total" in result.output
    assert "Line 5, column 3: monthly_budget.updated" in result.output
    assert "Line 6, column 3: monthly_budget.notes" in result.output


def test_budget_validate_recurring_savings_schema(tmp_path: Path) -> None:
    """recurring_savings entries should validate amount, dates, labels, and metadata."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 1000000",
                "  categories: {}",
                "recurring_savings:",
                "  - label: ''",
                "    amount: -1",
                "    frequency: someday",
                '    start_month: "2026-13"',
                '    end_date: "2026-02-30"',
                "    tags: ['', 123]",
                "    notes: 123",
                "    source:",
                "      system: bank",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "budget", "validate"])

    assert result.exit_code == 3, result.output
    assert "recurring_savings[0].label" in result.output
    assert "recurring_savings[0].amount" in result.output
    assert "recurring_savings[0].frequency" in result.output
    assert "recurring_savings[0].start_month" in result.output
    assert "recurring_savings[0].end_date" in result.output
    assert "recurring_savings[0].tags[0]" in result.output
    assert "recurring_savings[0].tags[1]" in result.output
    assert "recurring_savings[0].notes" in result.output
    assert "recurring_savings[0].source" in result.output


def test_budget_validate_financial_context_and_obligations_schema(tmp_path: Path) -> None:
    """financial_context and known_obligations should validate types, amounts, and dates."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 1000000",
                "  categories: {}",
                "financial_context:",
                "  income:",
                "    monthly_estimate: -1",
                '    as_of: "2026-02-30"',
                "  family:",
                "    household_size: 0",
                "    dependents_count: -1",
                "    notes: [not, text]",
                "  housing:",
                "    status: ''",
                "    monthly_payment: -1",
                "    deposit: many",
                "known_obligations:",
                "  - label: ''",
                "    amount: many",
                "    frequency: daily",
                '    date: "2026-02-30"',
                '    start_month: "2026-13"',
                '    start_date: "2026-04-01"',
                '    end_date: "2026-03-31"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "budget", "validate"])

    assert result.exit_code == 3, result.output
    assert "financial_context.income.monthly_estimate" in result.output
    assert "financial_context.income.as_of" in result.output
    assert "financial_context.family.household_size" in result.output
    assert "financial_context.family.dependents_count" in result.output
    assert "financial_context.family.notes" in result.output
    assert "financial_context.housing.status" in result.output
    assert "financial_context.housing.monthly_payment" in result.output
    assert "financial_context.housing.deposit" in result.output
    assert "known_obligations[0].label" in result.output
    assert "known_obligations[0].amount" in result.output
    assert "known_obligations[0].frequency" in result.output
    assert "known_obligations[0].date" in result.output
    assert "known_obligations[0].start_month" in result.output
    assert "known_obligations[0].end_date" in result.output


@pytest.mark.parametrize(
    "update",
    [
        "categories=1",
        "monthly_budget=1",
        "monthly_budget.categories=1",
        "updated=2026-04-20",
        "monthly_budget.updated=2026-04-20",
        "notes=freeze spending",
        "monthly_budget.notes=freeze spending",
    ],
)
def test_budget_edit_rejects_invalid_update_keys(
    budget_data_dir: Path,
    update: str,
) -> None:
    """Unsupported `budget edit --set` keys should fail with a usage error."""
    goals_path = budget_data_dir / "goals.yaml"
    before_text = goals_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(budget_data_dir),
            "budget",
            "edit",
            "--set",
            update,
            "--yes",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "Invalid budget key" in result.output
    assert goals_path.read_text(encoding="utf-8") == before_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04", "2026-04"),
        ("1999-01", "1999-01"),
        ("2099-12", "2099-12"),
    ],
)
def test_parse_budget_period_accepts_yyyy_mm(raw: str, expected: str) -> None:
    """Explicit period values should round-trip as YYYY-MM."""
    # Arrange / Act
    parsed = parse_budget_period(raw)

    # Assert
    assert parsed == expected


@pytest.mark.parametrize(
    "raw",
    [
        "2026-13",
        "2026-00",
        "2026/04",
        "2026-4",
        "26-04",
        "",
        "latest",
    ],
)
def test_parse_budget_period_rejects_invalid_values(raw: str) -> None:
    """Invalid period literals should raise the existing month-format error."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="expected YYYY-MM"):
        parse_budget_period(raw)


def test_latest_budget_window_returns_newest_partition(tmp_path: Path) -> None:
    """The default window should be the newest transactions.csv partition."""
    # Arrange
    csv_base_dir = tmp_path / "transactions"
    _touch_partition(csv_base_dir, "2026", "03")
    _touch_partition(csv_base_dir, "2026", "04")
    (csv_base_dir / "2026" / "05").mkdir(parents=True)
    (csv_base_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    # Act
    window = latest_budget_window(csv_base_dir)

    # Assert
    assert window == "2026-04"


def test_latest_budget_window_returns_none_without_partitions(tmp_path: Path) -> None:
    """Missing or empty partition roots should not invent a window."""
    # Arrange
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()

    # Act / Assert
    assert latest_budget_window(missing) is None
    assert latest_budget_window(empty) is None


def test_resolve_budget_period_prefers_explicit_month(tmp_path: Path) -> None:
    """`--month` should win over the latest partition window."""
    # Arrange
    csv_base_dir = tmp_path / "transactions"
    _touch_partition(csv_base_dir, "2026", "04")

    # Act
    resolved = resolve_budget_period("2026-03", csv_base_dir=csv_base_dir)

    # Assert
    assert resolved == "2026-03"


def test_resolve_budget_period_defaults_to_latest_window(tmp_path: Path) -> None:
    """Omitting `--month` should use the latest partition window."""
    # Arrange
    csv_base_dir = tmp_path / "transactions"
    _touch_partition(csv_base_dir, "2026", "03")
    _touch_partition(csv_base_dir, "2026", "04")

    # Act
    resolved = resolve_budget_period(None, csv_base_dir=csv_base_dir)

    # Assert
    assert resolved == "2026-04"


def test_resolve_budget_period_falls_back_to_today_without_window(tmp_path: Path) -> None:
    """An empty partition root should fall back to the local calendar month."""
    # Arrange
    csv_base_dir = tmp_path / "transactions"

    # Act
    resolved = resolve_budget_period(
        None,
        csv_base_dir=csv_base_dir,
        today=date(2026, 8, 27),
    )

    # Assert
    assert resolved == "2026-08"


def test_budget_status_can_navigate_historical_months(budget_data_dir: Path) -> None:
    """`--month` should switch actuals to the requested historical partition."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(budget_data_dir),
            "budget",
            "status",
            "--json",
            "--month",
            "2026-03",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    rows = {row["name"]: row for row in payload["categories"]}

    assert payload["_meta"]["month"] == "2026-03"
    assert payload["summary"]["actual"] == 50000
    assert rows["식비"]["actual"] == 30000
    assert rows["교통"]["actual"] == 20000
    assert rows["카페"]["actual"] == 0
    assert payload["health"] == {
        "status": "ok",
        "reasons": [],
    }
    assert payload["actionable"] is False
    assert payload["unmatched_goal_categories"] == []


def test_budget_status_defaults_to_latest_partition_window(budget_data_dir: Path) -> None:
    """Omitting `--month` should report the latest partition in JSON and human output."""
    # Arrange / Act
    json_result = runner.invoke(
        app,
        ["--data-dir", str(budget_data_dir), "budget", "status", "--json"],
    )
    human_result = runner.invoke(
        app,
        ["--data-dir", str(budget_data_dir), "budget", "status"],
    )

    # Assert
    assert json_result.exit_code == 0, json_result.output
    assert human_result.exit_code == 0, human_result.output
    payload = json.loads(json_result.output)
    assert payload["_meta"]["month"] == "2026-04"
    assert payload["month"] == "2026-04"
    assert "2026-04" in human_result.output


def test_budget_status_invalid_month_is_usage_error(budget_data_dir: Path) -> None:
    """Invalid `--month` should keep JSON/human usage-error semantics."""
    # Arrange
    args = ["--data-dir", str(budget_data_dir), "budget", "status", "--month", "2026-13"]

    # Act
    json_result = runner.invoke(app, [*args, "--json"])
    human_result = runner.invoke(app, args)

    # Assert
    assert json_result.exit_code == ExitCode.USAGE_ERROR, json_result.output
    payload = json.loads(json_result.output)
    assert payload["_meta"]["command"] == "budget status"
    assert payload["error"]["code"] == ErrorCode.INVALID_ARGS
    assert "expected YYYY-MM" in payload["error"]["message"]

    assert human_result.exit_code == ExitCode.USAGE_ERROR, human_result.output
    assert "Invalid month value for 'month': 2026-13" in human_result.output
    assert "expected YYYY-MM" in human_result.output


def test_budget_status_flags_unmatched_goal_category_names(tmp_path: Path) -> None:
    """Stale goals names should warn instead of silently showing actual=0 / target=0."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 130000",
                "  categories:",
                "    식비: 100000",
                "    카페: 30000",
                '  updated: "2026-04-15"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_month(
        data_dir,
        pl.DataFrame(
            [
                _transaction_row("2026-04-02", -50_000, "식비", "Grocer"),
                _transaction_row("2026-04-04", -40_000, "카페/간식", "Cafe"),
            ]
        ),
        "2026",
        "04",
    )

    json_result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "status", "--json", "--month", "2026-04"],
    )
    human_result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "budget", "status", "--month", "2026-04"],
    )

    assert json_result.exit_code == 0, json_result.output
    assert human_result.exit_code == 0, human_result.output
    payload = json.loads(json_result.output)
    rows = {row["name"]: row for row in payload["categories"]}

    assert rows["식비"]["actual"] == 50_000
    assert rows["카페"] == {
        "name": "카페",
        "target": 30_000,
        "actual": 0,
        "remaining": 30_000,
        "progress_pct": 0.0,
        "status": "under",
    }
    assert rows["카페/간식"] == {
        "name": "카페/간식",
        "target": 0,
        "actual": 40_000,
        "remaining": -40_000,
        "progress_pct": None,
        "status": "over",
    }
    assert payload["unmatched_goal_categories"] == [
        {"name": "카페", "actual": 0, "suggested": ["카페/간식"]},
    ]
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["unbudgeted_spend", "unmatched_goal_categories"],
    }
    assert payload["review"]["unbudgeted_categories"] == ["카페/간식"]
    assert payload["next_steps"][0]["signal"] == "unbudgeted_spend"
    assert payload["next_steps"][1] == {
        "signal": "unmatched_goal_categories",
        "message": "Rename goals.yaml categories so they exactly match category_final values.",
        "command": "finjuice budget edit --help",
    }
    assert "Goals categories not matching any spend category: 카페" in human_result.output
    assert "카페/간식" in human_result.output
    assert "finjuice budget edit --set" in human_result.output


def test_budget_status_honors_report_filters_and_no_filter_override(
    report_filters_data_dir: Path,
) -> None:
    """Budget actuals should use shared report_filters and recompute on `--no-filter`."""
    (report_filters_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 450000",
                "  categories:",
                "    의료: 100000",
                "    생활: 300000",
                "    식비: 50000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    filtered_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "budget",
            "status",
            "--json",
            "--month",
            "2024-10",
        ],
    )
    no_filter_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(report_filters_data_dir),
            "--no-filter",
            "budget",
            "status",
            "--json",
            "--month",
            "2024-10",
        ],
    )

    assert filtered_result.exit_code == 0, filtered_result.output
    assert no_filter_result.exit_code == 0, no_filter_result.output

    filtered_payload = json.loads(filtered_result.output)
    no_filter_payload = json.loads(no_filter_result.output)
    filtered_rows = {row["name"]: row for row in filtered_payload["categories"]}
    no_filter_rows = {row["name"]: row for row in no_filter_payload["categories"]}

    assert filtered_payload["_meta"]["filters_applied"] == 3
    assert filtered_payload["summary"]["actual"] == 50000
    assert filtered_rows["의료"]["actual"] == 0
    assert filtered_rows["생활"]["actual"] == 0
    assert filtered_rows["식비"]["actual"] == 50000

    assert no_filter_payload["_meta"]["filters_applied"] == 0
    assert no_filter_payload["summary"]["actual"] == 450000
    assert no_filter_rows["의료"]["actual"] == 100000
    assert no_filter_rows["생활"]["actual"] == 300000
    assert no_filter_rows["식비"]["actual"] == 50000


def _transaction_row(
    date: str,
    amount: int,
    category: str,
    merchant: str,
    *,
    is_transfer: int = 0,
    type_norm: str = "expense",
    type_raw: str = "승인",
) -> dict[str, object]:
    """Create a minimal row compatible with budget aggregation."""
    return {
        "row_hash": f"{date}-{merchant}-{amount}",
        "date": date,
        "time": "09:00",
        "datetime": f"{date}T09:00:00",
        "type_raw": type_raw,
        "type_norm": type_norm,
        "merchant_raw": merchant,
        "amount": amount,
        "account": "테스트카드",
        "category_final": category,
        "tags_final": "[]",
        "is_transfer": is_transfer,
        "currency": "KRW",
    }


def _write_month(data_dir: Path, df: pl.DataFrame, year: str, month: str) -> None:
    """Write one transactions.csv partition."""
    month_dir = data_dir / "transactions" / year / month
    month_dir.mkdir(parents=True)
    df.write_csv(month_dir / "transactions.csv")


def _touch_partition(csv_base_dir: Path, year: str, month: str) -> None:
    """Create an empty transactions.csv partition for window discovery tests."""
    path = csv_base_dir / year / month / "transactions.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("row_hash\n", encoding="utf-8")
