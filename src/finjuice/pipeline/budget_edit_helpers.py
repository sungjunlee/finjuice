"""YAML edit helpers for monthly budget round-trip updates.

Owns --set KEY=VALUE parsing, nested mapping bootstrapping, and monthly-budget
serialization. Public ``compute_budget_edit`` stays in
:mod:`finjuice.pipeline.budget_compute`, which re-exports the public names used
by existing callers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ruamel.yaml.comments import CommentedMap

from finjuice.pipeline.goals import MonthlyBudget

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
