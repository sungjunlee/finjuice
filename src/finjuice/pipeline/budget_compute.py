"""Budget status, edit, and validate computation independent of Typer CLI."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import polars as pl
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_non_consumption_for, exclude_transfers_for
from finjuice.pipeline.goals import (
    GoalsValidationProblem,
    MonthlyBudget,
    load_goals_file,
    load_goals_roundtrip,
    new_goals_document,
    validate_goals_payload,
    write_goals_roundtrip,
)
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA, get_partition_path
from finjuice.pipeline.tagging.models import ReportFilters

logger = logging.getLogger(__name__)

STATUS_ON_TRACK_MIN_PCT = 90.0
BUDGET_EDIT_UPDATE_HINT = (
    "Use total=..., categories.<name>=..., monthly_budget.categories.<name>=..., "
    "or bare category names such as 식비=700000."
)
_RESERVED_BUDGET_EDIT_KEYS = {
    "categories",
    "monthly_budget",
    "monthly_budget.categories",
    "updated",
    "monthly_budget.updated",
    "notes",
    "monthly_budget.notes",
    "version",
}

ReportFiltersLoader = Callable[[], ReportFilters]
BudgetEditConfirm = Callable[[int], bool]

__all__ = [
    "BUDGET_EDIT_UPDATE_HINT",
    "BudgetEditCancelledError",
    "GoalsFileInvalidError",
    "STATUS_ON_TRACK_MIN_PCT",
    "compute_budget_edit",
    "compute_budget_status",
    "compute_budget_validate",
]


class GoalsFileInvalidError(Exception):
    """Raised when goals.yaml exists but cannot be used as a budget document."""

    def __init__(self, problems: list[GoalsValidationProblem]) -> None:
        self.problems = problems
        super().__init__("goals.yaml is invalid")


class BudgetEditCancelledError(Exception):
    """Raised when the caller declines to write a prepared budget edit."""


def compute_budget_status(
    config: Config,
    *,
    month: str,
    load_report_filters: ReportFiltersLoader,
) -> dict[str, Any]:
    """Compute the budget status payload for one resolved month.

    Args:
        config: Runtime configuration with goals and CSV paths.
        month: Resolved ``YYYY-MM`` budget period.
        load_report_filters: Lazy loader invoked only when the month partition
            exists, so missing-partition runs do not validate ``rules.yaml``.
    """
    goals_result = load_goals_file(config.goals_file)
    goals_file = {
        "path": str(config.goals_file),
        "exists": goals_result.exists,
    }

    if not goals_result.exists:
        _, filters_applied = _load_budget_actuals(
            config,
            month=month,
            load_report_filters=load_report_filters,
        )
        return {
            "month": month,
            "goals_file": goals_file,
            "summary": None,
            "categories": [],
            "unmatched_goal_categories": [],
            **_build_budget_guidance(
                month=month,
                goals_exists=False,
                summary=None,
                category_rows=[],
                extras={"filters_applied": filters_applied, "unmatched_goal_categories": []},
            ),
            "_filters_applied": filters_applied,
        }

    if goals_result.document is None:
        raise GoalsFileInvalidError(goals_result.problems)

    assert goals_result.document is not None
    budget = goals_result.document.monthly_budget
    actuals, filters_applied = _load_budget_actuals(
        config,
        month=month,
        load_report_filters=load_report_filters,
    )

    category_rows = _build_category_rows(budget, actuals)
    unmatched_goal_categories = _unmatched_goal_categories(budget, actuals)
    summary = _build_summary_row(budget, actuals)
    goals_file["updated"] = budget.updated
    goals_file["notes"] = budget.notes

    return {
        "month": month,
        "goals_file": goals_file,
        "summary": summary,
        "categories": category_rows,
        "unmatched_goal_categories": unmatched_goal_categories,
        **_build_budget_guidance(
            month=month,
            goals_exists=True,
            summary=summary,
            category_rows=category_rows,
            extras={
                "filters_applied": filters_applied,
                "unmatched_goal_categories": unmatched_goal_categories,
            },
        ),
        "_filters_applied": filters_applied,
    }


def compute_budget_edit(
    config: Config,
    *,
    updates: list[str],
    confirm: BudgetEditConfirm | None = None,
) -> dict[str, Any]:
    """Apply round-trip goals.yaml edits after validation.

    Args:
        config: Runtime configuration with the goals file path.
        updates: Raw ``KEY=VALUE`` edit strings from ``budget edit --set``.
        confirm: Optional confirmation callback receiving the change count.
            When omitted, the write proceeds without prompting.
    """
    try:
        yaml, loaded = load_goals_roundtrip(config.goals_file)
    except (OSError, YAMLError) as exc:
        raise GoalsFileInvalidError([_parse_problem_from_exception(exc)]) from exc

    if loaded is None:
        document = new_goals_document()
    elif not isinstance(loaded, CommentedMap):
        raise GoalsFileInvalidError(
            [
                GoalsValidationProblem(
                    path="goals.yaml",
                    message="must contain a mapping",
                )
            ]
        )
    else:
        document = loaded

    _bootstrap_budget_document(document)

    changes = [_apply_budget_update(document, item) for item in updates]
    validated_document, problems = validate_goals_payload(document)
    if validated_document is None:
        raise GoalsFileInvalidError(problems)
    assert validated_document is not None

    if confirm is not None and not confirm(len(changes)):
        raise BudgetEditCancelledError()

    write_goals_roundtrip(yaml, document, config.goals_file)
    return {
        "path": str(config.goals_file),
        "changes": changes,
        "monthly_budget": _serialize_monthly_budget(validated_document.monthly_budget),
    }


def compute_budget_validate(config: Config) -> dict[str, Any]:
    """Validate goals.yaml and build a renderable payload."""
    result = load_goals_file(config.goals_file)
    if not result.exists:
        problems = [
            GoalsValidationProblem(
                path=str(config.goals_file),
                message="file not found",
            )
        ]
        return {
            "status": "invalid",
            "path": str(config.goals_file),
            "problems": [_serialize_problem(problem) for problem in problems],
            "_problems": problems,
            "_has_errors": True,
        }

    problems = result.problems
    return {
        "status": "valid" if not problems else "invalid",
        "path": str(config.goals_file),
        "problems": [_serialize_problem(problem) for problem in problems],
        "_problems": problems,
        "_has_errors": bool(problems),
    }


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


def _apply_budget_update(document: CommentedMap, raw_update: str) -> dict[str, Any]:
    """Apply one --set KEY=VALUE edit to the round-trip YAML document."""
    if "=" not in raw_update:
        raise ValueError(f"Invalid --set format: {raw_update} (expected key=value)")
    raw_key, raw_value = raw_update.split("=", 1)
    key = raw_key.strip()
    if not key:
        raise ValueError(f"Invalid --set format: {raw_update} (empty key)")

    monthly_budget = _ensure_mapping(document, "monthly_budget")
    categories = _ensure_mapping(monthly_budget, "categories")

    if key == "total" or key == "monthly_budget.total":
        old_value = monthly_budget.get("total")
        monthly_budget["total"] = _parse_budget_int(raw_value, key="monthly_budget.total")
        return {"path": "monthly_budget.total", "old": old_value, "new": monthly_budget["total"]}

    if key in _RESERVED_BUDGET_EDIT_KEYS:
        raise ValueError(f"Invalid budget key: {key}. {BUDGET_EDIT_UPDATE_HINT}")

    category_name = key
    if key.startswith("monthly_budget."):
        if not key.startswith("monthly_budget.categories."):
            raise ValueError(f"Invalid budget key: {key}. {BUDGET_EDIT_UPDATE_HINT}")
        category_name = key.removeprefix("monthly_budget.categories.")
    elif key.startswith("categories."):
        category_name = key.removeprefix("categories.")
    category_name = category_name.strip()
    if not category_name:
        raise ValueError(f"Invalid budget key: {key}. {BUDGET_EDIT_UPDATE_HINT}")

    old_value = categories.get(category_name)
    categories[category_name] = _parse_budget_int(
        raw_value,
        key=f"monthly_budget.categories.{category_name}",
    )
    return {
        "path": f"monthly_budget.categories.{category_name}",
        "old": old_value,
        "new": categories[category_name],
    }


def _ensure_mapping(parent: CommentedMap, key: str) -> CommentedMap:
    """Ensure a nested mapping exists inside a round-trip YAML document."""
    current = parent.get(key)
    if current is None:
        current = CommentedMap()
        parent[key] = current
    if not isinstance(current, CommentedMap):
        if isinstance(current, dict):
            current = CommentedMap(current)
            parent[key] = current
        else:
            raise ValueError(f"{key} must be a mapping before it can be edited")
    return current


def _bootstrap_budget_document(document: CommentedMap) -> None:
    """Ensure the minimum monthly_budget skeleton exists for edits."""
    if "version" not in document:
        document.insert(0, "version", 1)

    monthly_budget = _ensure_mapping(document, "monthly_budget")
    if "total" not in monthly_budget:
        monthly_budget.insert(0, "total", 0)
    _ensure_mapping(monthly_budget, "categories")


def _parse_budget_int(raw_value: str, *, key: str) -> int:
    """Parse a non-negative integer budget value."""
    stripped = raw_value.strip()
    try:
        value = int(stripped)
    except ValueError as exc:
        raise ValueError(f"{key} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _serialize_monthly_budget(monthly_budget: MonthlyBudget) -> dict[str, Any]:
    """Serialize the validated monthly budget payload."""
    return {
        "total": monthly_budget.total,
        "categories": dict(monthly_budget.categories),
        "updated": monthly_budget.updated,
        "notes": monthly_budget.notes,
    }


def _serialize_problem(problem: GoalsValidationProblem) -> dict[str, Any]:
    """Serialize a validation problem for JSON output."""
    return {
        "path": problem.path,
        "message": problem.message,
        "line": problem.line,
        "column": problem.column,
        "formatted": problem.format(),
    }


def _parse_problem_from_exception(exc: Exception) -> GoalsValidationProblem:
    """Build a line-numbered problem from a YAML parser exception."""
    mark = getattr(exc, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    detail = getattr(exc, "problem", None) or "failed to parse YAML"
    return GoalsValidationProblem(
        path="goals.yaml",
        message=str(detail),
        line=(line + 1) if isinstance(line, int) else None,
        column=(column + 1) if isinstance(column, int) else None,
    )
