"""Status compute helpers for monthly budget vs actuals.

Owns partition actuals loading, category/summary rows, unmatched-goal matching,
and health/guidance construction. Public ``compute_budget_status`` stays in
:mod:`finjuice.pipeline.budget_compute`, which re-exports the public names used
by existing callers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import polars as pl

from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_non_consumption_for, exclude_transfers_for
from finjuice.pipeline.goals import MonthlyBudget
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA, get_partition_path
from finjuice.pipeline.tagging.models import ReportFilters

logger = logging.getLogger(__name__)

STATUS_ON_TRACK_MIN_PCT = 90.0

ReportFiltersLoader = Callable[[], ReportFilters]


def _load_budget_actuals(
    config: Config,
    *,
    month: str,
    load_report_filters: ReportFiltersLoader,
) -> tuple[dict[str, int], int]:
    """Load one month's filtered expense actuals by category."""
    year, month_value = month.split("-", 1)
    partition_path = get_partition_path(config.csv_base_dir, int(year), int(month_value))
    if not partition_path.exists():
        return {}, 0

    try:
        source_df = pl.read_csv(
            partition_path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
        )
    except (FileNotFoundError, pl.exceptions.PolarsError, OSError) as exc:
        logger.warning("Could not read budget partition %s: %s", partition_path, exc)
        return {}, 0

    report_filters = load_report_filters()
    filtered_df, filters_applied = apply_report_filters(source_df, report_filters)
    expense_df = _expense_rows(filtered_df)
    if expense_df.is_empty():
        return {}, filters_applied

    grouped = (
        expense_df.with_columns(_budget_category_expr(expense_df).alias("budget_category"))
        .group_by("budget_category")
        .agg(pl.col("amount").abs().sum().alias("actual_amount"))
        .sort("actual_amount", descending=True)
    )
    actuals = {str(row[0]): int(round(float(row[1]))) for row in grouped.iter_rows()}
    return actuals, filters_applied


def _expense_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Return consumption expense rows, excluding transfers and non-consumption."""
    if df.is_empty() or "amount" not in df.columns:
        return df.head(0)

    expr = pl.col("amount") < 0
    if "type_norm" in df.columns:
        expr = expr & (pl.col("type_norm").cast(pl.Utf8, strict=False) == "expense")
    expr = expr & exclude_transfers_for(df) & exclude_non_consumption_for(df)
    return df.filter(expr)


def _budget_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build the category fallback chain used for budget rollups."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8, strict=False))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])


def _build_category_rows(
    monthly_budget: MonthlyBudget,
    actuals: dict[str, int],
) -> list[dict[str, Any]]:
    """Build per-category rows from configured budgets plus unbudgeted spend."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, target in monthly_budget.categories.items():
        actual = actuals.get(name, 0)
        rows.append(_status_row(name, target, actual))
        seen.add(name)

    unbudgeted = [
        (name, actual) for name, actual in actuals.items() if name not in seen and actual > 0
    ]
    for name, actual in sorted(unbudgeted, key=lambda item: (-item[1], item[0])):
        rows.append(_status_row(name, 0, actual))

    return rows


def _unmatched_goal_categories(
    monthly_budget: MonthlyBudget,
    actuals: dict[str, int],
) -> list[dict[str, Any]]:
    """List goal names that do not bind to this month's spend categories.

    A configured name is unmatched when it is absent from ``actuals`` and that
    absence is not just a quiet month: leftover spend exists under names that
    did not bind to any goal.
    """
    unbudgeted_names = [
        name
        for name, amount in actuals.items()
        if name not in monthly_budget.categories and amount > 0
    ]
    if not unbudgeted_names:
        return []

    unmatched: list[dict[str, Any]] = []
    for name in monthly_budget.categories:
        if name in actuals:
            continue
        unmatched.append(
            {
                "name": name,
                "actual": 0,
                "suggested": _suggested_spend_categories(name, unbudgeted_names),
            }
        )
    return unmatched


def _suggested_spend_categories(goal_name: str, spend_names: list[str]) -> list[str]:
    """Return unbudgeted spend names that look like a renamed form of ``goal_name``."""
    return sorted(
        spend_name
        for spend_name in spend_names
        if goal_name in spend_name or spend_name in goal_name
    )


def _build_summary_row(monthly_budget: MonthlyBudget, actuals: dict[str, int]) -> dict[str, Any]:
    """Build the overall budget summary row."""
    total_actual = sum(actuals.values())
    return _status_row("Total", monthly_budget.total, total_actual)


def _status_row(name: str, target: int, actual: int) -> dict[str, Any]:
    """Build one budget status row."""
    remaining = target - actual
    progress_pct = round((actual / target) * 100, 2) if target > 0 else None
    status = _budget_status(progress_pct=progress_pct, target=target, actual=actual)
    return {
        "name": name,
        "target": target,
        "actual": actual,
        "remaining": remaining,
        "progress_pct": progress_pct,
        "status": status,
    }


def _build_budget_guidance(
    *,
    month: str,
    goals_exists: bool,
    summary: dict[str, Any] | None,
    category_rows: list[dict[str, Any]],
    extras: dict[str, Any],
) -> dict[str, Any]:
    """Build additive health/action cues for budget status.

    ``extras`` carries ``filters_applied`` (int) and
    ``unmatched_goal_categories`` (list of dicts) so the call surface stays
    under the repo's function-argument ratchet.
    """
    filters_applied = extras.get("filters_applied", 0)
    unmatched_goal_categories = extras.get("unmatched_goal_categories") or []
    over_budget_count = sum(
        1 for row in category_rows if row["status"] == "over" and row["target"] > 0
    )
    unbudgeted_count = sum(1 for row in category_rows if row["target"] == 0 and row["actual"] > 0)
    on_track_count = sum(1 for row in category_rows if row["status"] == "on-track")
    under_budget_count = sum(1 for row in category_rows if row["status"] == "under")
    over_budget_categories = [
        row["name"] for row in category_rows if row["status"] == "over" and row["target"] > 0
    ]
    unbudgeted_categories = [
        row["name"] for row in category_rows if row["target"] == 0 and row["actual"] > 0
    ]
    at_risk_categories = [
        row["name"]
        for row in category_rows
        if row["status"] in {"on-track", "over"} or (row["target"] == 0 and row["actual"] > 0)
    ]

    reasons: list[str] = []
    if not goals_exists:
        reasons.append("missing_goals_file")
    else:
        if over_budget_count > 0:
            reasons.append("over_budget_categories")
        if unbudgeted_count > 0:
            reasons.append("unbudgeted_spend")
        if unmatched_goal_categories:
            reasons.append("unmatched_goal_categories")

    next_steps: list[dict[str, str]] = []
    if not goals_exists:
        next_steps.append(
            {
                "signal": "missing_goals_file",
                "message": "Create monthly budget targets before relying on budget status.",
                "command": "finjuice budget edit --help",
            }
        )
    elif reasons:
        if "over_budget_categories" in reasons or "unbudgeted_spend" in reasons:
            review_signal = (
                "over_budget_categories"
                if "over_budget_categories" in reasons
                else "unbudgeted_spend"
            )
            next_steps.append(
                {
                    "signal": review_signal,
                    "message": "Inspect this month's review queue before changing the budget.",
                    "command": f"finjuice review --json --month {month}",
                }
            )
        if "unmatched_goal_categories" in reasons:
            next_steps.append(
                {
                    "signal": "unmatched_goal_categories",
                    "message": (
                        "Rename goals.yaml categories so they exactly match category_final values."
                    ),
                    "command": "finjuice budget edit --help",
                }
            )
        next_steps.append(
            {
                "signal": "budget_adjustment",
                "message": "Update goals.yaml targets when the current budget is outdated.",
                "command": "finjuice budget edit --help",
            }
        )

    return {
        "health": {
            "status": "critical" if not goals_exists else "warning" if reasons else "ok",
            "reasons": reasons,
        },
        "actionable": bool(reasons),
        "signals": {
            "goals_file_exists": goals_exists,
            "over_budget_count": over_budget_count,
            "unbudgeted_count": unbudgeted_count,
            "on_track_count": on_track_count,
            "under_budget_count": under_budget_count,
            "remaining_total": None if summary is None else summary["remaining"],
            "filters_applied": filters_applied,
        },
        "review": {
            "month": month,
            "target": None if summary is None else summary["target"],
            "actual": None if summary is None else summary["actual"],
            "remaining": None if summary is None else summary["remaining"],
            "at_risk_categories": at_risk_categories,
            "over_budget_categories": over_budget_categories,
            "unbudgeted_categories": unbudgeted_categories,
        },
        "next_steps": next_steps,
    }


def _budget_status(*, progress_pct: float | None, target: int, actual: int) -> str:
    """Return the status enum for one budget row."""
    if target <= 0:
        return "over" if actual > 0 else "on-track"
    if progress_pct is None:
        return "under"
    if progress_pct > 100.0:
        return "over"
    if progress_pct >= STATUS_ON_TRACK_MIN_PCT:
        return "on-track"
    return "under"
