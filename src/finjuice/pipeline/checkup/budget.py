"""Budget posture collector for the checkup bundle."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import yaml

from finjuice.pipeline.checkup.models import BudgetPostureSummary, BudgetSummary
from finjuice.pipeline.checkup.partitions import (
    expense_rows,
    latest_partition_month,
    read_month_partition,
)
from finjuice.pipeline.checkup.values import merge_warning
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import MonthlyBudget, load_goals_file
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters


def collect_budget_posture(
    config: Config,
    *,
    today: date,
) -> BudgetPostureSummary:
    """Summarize monthly budget posture without routing through the CLI command."""
    month = latest_partition_month(config.csv_base_dir) or today.strftime("%Y-%m")
    goals_result = load_goals_file(config.goals_file)
    actuals, filters_applied, filter_warning = _load_budget_actuals(config, month=month)

    if not goals_result.exists:
        warning = "goals.yaml not found. Budget posture is unconfigured."
        return BudgetPostureSummary(
            status="missing_config",
            actionable=True,
            month=month,
            goals_file_exists=False,
            filters_applied=filters_applied,
            summary=None,
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning=merge_warning(filter_warning, warning),
        )

    if goals_result.document is None:
        formatted = "; ".join(problem.format() for problem in goals_result.problems)
        warning = f"goals.yaml is invalid. {formatted}" if formatted else "goals.yaml is invalid."
        return BudgetPostureSummary(
            status="invalid",
            actionable=True,
            month=month,
            goals_file_exists=True,
            filters_applied=filters_applied,
            summary=None,
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning=merge_warning(filter_warning, warning),
        )

    summary = _build_budget_summary(goals_result.document.monthly_budget, actuals)
    category_rows = _build_budget_categories(goals_result.document.monthly_budget, actuals)
    over_budget_categories = [
        row["name"] for row in category_rows if row["status"] == "over" and row["target"] > 0
    ]
    unbudgeted_categories = [
        row["name"] for row in category_rows if row["target"] == 0 and row["actual"]
    ]

    status = "healthy" if summary.status in {"under", "on-track"} else "needs_attention"
    actionable = status == "needs_attention"

    return BudgetPostureSummary(
        status=status,
        actionable=actionable,
        month=month,
        goals_file_exists=True,
        filters_applied=filters_applied,
        summary=summary,
        over_budget_categories=over_budget_categories,
        unbudgeted_categories=unbudgeted_categories,
        warning=filter_warning,
    )


def _load_budget_actuals(
    config: Config,
    *,
    month: str,
) -> tuple[dict[str, int], int, str | None]:
    """Load one month's filtered expense actuals by category."""
    df = read_month_partition(config.csv_base_dir, month)
    if df is None or df.is_empty():
        return {}, 0, None

    report_filters, warning = _load_budget_report_filters(config)
    filtered_df, filters_applied = apply_report_filters(df, report_filters)
    expense_df = expense_rows(filtered_df)
    if expense_df.is_empty():
        return {}, filters_applied, warning

    grouped = (
        expense_df.with_columns(_budget_category_expr(expense_df).alias("budget_category"))
        .group_by("budget_category")
        .agg(pl.col("amount").abs().sum().alias("actual_amount"))
        .sort("actual_amount", descending=True)
    )
    actuals = {str(row[0]): int(round(float(row[1]))) for row in grouped.iter_rows()}
    return actuals, filters_applied, warning


def _load_budget_report_filters(config: Config) -> tuple[ReportFilters, str | None]:
    """Best-effort report-filter loader for runtime budget posture collection."""
    try:
        return load_report_filters(config.rules_file), None
    except (OSError, yaml.YAMLError) as exc:
        return ReportFilters(), f"Could not load report filters for budget posture: {exc}"


def _budget_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build the category fallback chain used for budget rollups."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8, strict=False))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])


def _build_budget_categories(
    monthly_budget: MonthlyBudget,
    actuals: dict[str, int],
) -> list[dict[str, Any]]:
    """Build per-category rows from configured budgets plus unbudgeted spend."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, target in monthly_budget.categories.items():
        rows.append(_budget_row(name, target, actuals.get(name, 0)))
        seen.add(name)

    unbudgeted = [
        (name, actual) for name, actual in actuals.items() if name not in seen and actual > 0
    ]
    for name, actual in sorted(unbudgeted, key=lambda item: (-item[1], item[0])):
        rows.append(_budget_row(name, 0, actual))

    return rows


def _build_budget_summary(monthly_budget: MonthlyBudget, actuals: dict[str, int]) -> BudgetSummary:
    """Build the overall budget summary row."""
    row = _budget_row("Total", monthly_budget.total, sum(actuals.values()))
    return BudgetSummary(
        target=row["target"],
        actual=row["actual"],
        remaining=row["remaining"],
        progress_pct=row["progress_pct"],
        status=row["status"],
    )


def _budget_row(name: str, target: int, actual: int) -> dict[str, Any]:
    """Return one normalized budget-status row."""
    progress_pct = round((actual / target) * 100, 2) if target > 0 else None
    return {
        "name": name,
        "target": target,
        "actual": actual,
        "remaining": target - actual,
        "progress_pct": progress_pct,
        "status": _budget_status(progress_pct=progress_pct, target=target, actual=actual),
    }


def _budget_status(*, progress_pct: float | None, target: int, actual: int) -> str:
    """Return the normalized budget posture enum."""
    if target <= 0:
        return "over" if actual > 0 else "on-track"
    if progress_pct is None:
        return "under"
    if progress_pct > 100.0:
        return "over"
    if progress_pct >= 90.0:
        return "on-track"
    return "under"
