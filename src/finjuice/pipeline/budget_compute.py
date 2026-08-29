"""Budget status, edit, and validate computation independent of Typer CLI.

Status actuals, category/summary rows, unmatched-goal matching, and guidance
helpers live in :mod:`finjuice.pipeline.budget_status_helpers` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.budget_status_helpers import (
    STATUS_ON_TRACK_MIN_PCT,  # noqa: F401 — re-exported for existing budget imports
    ReportFiltersLoader,
    _budget_category_expr,  # noqa: F401 — re-exported for existing budget imports
    _budget_status,  # noqa: F401 — re-exported for existing budget imports
    _build_budget_guidance,
    _build_category_rows,
    _build_summary_row,
    _expense_rows,  # noqa: F401 — re-exported for existing budget imports
    _load_budget_actuals,
    _status_row,  # noqa: F401 — re-exported for existing budget imports
    _suggested_spend_categories,  # noqa: F401 — re-exported for existing budget imports
    _unmatched_goal_categories,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import (
    GoalsValidationProblem,
    MonthlyBudget,
    load_goals_file,
    load_goals_roundtrip,
    new_goals_document,
    validate_goals_payload,
    write_goals_roundtrip,
)

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
