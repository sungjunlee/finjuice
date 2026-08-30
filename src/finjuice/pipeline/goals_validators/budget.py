"""Monthly-budget section validators for goals.yaml.

Owns ``monthly_budget`` mapping/shape checks. Field-level helpers stay in
``fields.py``. Payload orchestration stays in ``validate.py``, which
re-exports these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.goals_validators.fields import _is_non_negative_int, _problem
from finjuice.pipeline.goals_validators.models import (
    DATE_LITERAL_PATTERN,
    MonthlyBudget,
    ValidationProblems,
)


def _validate_monthly_budget_mapping(
    payload: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[Any, Any] | None:
    """Return the monthly_budget mapping or record a fatal section problem."""
    budget_value = payload.get("monthly_budget")
    if budget_value is None:
        problems.append(_problem("monthly_budget", "missing required key", payload))
        return None
    if not isinstance(budget_value, dict):
        problems.append(
            _problem("monthly_budget", "must be a mapping", payload, key="monthly_budget")
        )
        return None
    return budget_value


def _validate_monthly_budget(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> MonthlyBudget | None:
    """Validate the required monthly_budget section."""
    total = _validate_budget_total(budget_value, problems)
    categories = _validate_budget_categories(budget_value, problems)
    updated = _validate_budget_updated(budget_value, problems)
    notes = _validate_budget_notes(budget_value, problems)
    if total is None or categories is None:
        return None
    return MonthlyBudget(total=total, categories=categories, updated=updated, notes=notes)


def _validate_budget_total(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> int | None:
    """Validate monthly_budget.total."""
    total_value = budget_value.get("total")
    if total_value is None:
        problems.append(_problem("monthly_budget.total", "missing required key", budget_value))
        return None
    if not _is_non_negative_int(total_value):
        problems.append(
            _problem(
                "monthly_budget.total",
                "must be a non-negative integer",
                budget_value,
                key="total",
            )
        )
        return None
    return int(total_value)


def _validate_budget_categories(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[str, int] | None:
    """Validate monthly_budget.categories."""
    categories_value = budget_value.get("categories")
    if categories_value is None:
        problems.append(_problem("monthly_budget.categories", "missing required key", budget_value))
        return None
    if not isinstance(categories_value, dict):
        problems.append(
            _problem(
                "monthly_budget.categories",
                "must be a mapping of category name -> non-negative integer",
                budget_value,
                key="categories",
            )
        )
        return None
    return _validate_budget_category_values(categories_value, problems)


def _validate_budget_category_values(
    categories_value: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[str, int]:
    """Validate each category target in monthly_budget.categories."""
    categories: dict[str, int] = {}
    for category_name, amount in categories_value.items():
        category_path = f"monthly_budget.categories.{category_name}"
        if not isinstance(category_name, str) or not category_name.strip():
            problems.append(
                _problem(
                    "monthly_budget.categories",
                    "category names must be non-empty strings",
                    categories_value,
                    key=category_name,
                )
            )
            continue
        if not _is_non_negative_int(amount):
            problems.append(
                _problem(
                    category_path,
                    "must be a non-negative integer",
                    categories_value,
                    key=category_name,
                )
            )
            continue
        categories[category_name] = int(amount)
    return categories


def _validate_budget_updated(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> str | None:
    """Validate monthly_budget.updated."""
    updated_value = budget_value.get("updated")
    if updated_value is None:
        return None
    if not isinstance(updated_value, str) or not DATE_LITERAL_PATTERN.match(updated_value):
        problems.append(
            _problem(
                "monthly_budget.updated",
                "must use YYYY-MM-DD format",
                budget_value,
                key="updated",
            )
        )
        return None
    try:
        date.fromisoformat(updated_value)
    except ValueError:
        problems.append(
            _problem(
                "monthly_budget.updated",
                "must be a real calendar date in YYYY-MM-DD format",
                budget_value,
                key="updated",
            )
        )
        return None
    return updated_value


def _validate_budget_notes(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> str | None:
    """Validate monthly_budget.notes."""
    notes_value = budget_value.get("notes")
    if notes_value is None:
        return None
    if not isinstance(notes_value, str):
        problems.append(
            _problem(
                "monthly_budget.notes",
                "must be a string",
                budget_value,
                key="notes",
            )
        )
        return None
    return notes_value
