"""Field-level helpers for goals.yaml validation.

Section validators stay in ``validate.py``. Monthly-budget section helpers
live in ``budget.py``. Financial-context section helpers live in
``context.py``. This module owns scalar field checks.

Problem construction with source locations lives in
:mod:`finjuice.pipeline.goals_validators.fields_helpers`. Date/month ranges
live in :mod:`finjuice.pipeline.goals_validators.fields_ranges`. Both are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.goals_validators.fields_helpers import (
    _parse_error_problem,  # noqa: F401 — re-exported for existing fields imports
    _position,  # noqa: F401 — re-exported for existing fields imports
    _problem,
)
from finjuice.pipeline.goals_validators.fields_ranges import (
    _validate_date_range,  # noqa: F401 — re-exported for existing fields imports
    _validate_month_range,  # noqa: F401 — re-exported for existing fields imports
    _validate_optional_date,  # noqa: F401 — re-exported for existing fields imports
    _validate_optional_month,  # noqa: F401 — re-exported for existing fields imports
)
from finjuice.pipeline.goals_validators.models import (
    RECURRING_SAVINGS_FREQUENCIES,
    ValidationProblems,
)


def _is_non_negative_int(value: Any) -> bool:
    """Return True when a value is a non-negative integer (but not bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_required_label(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> str | None:
    """Validate a required non-empty label field."""
    label_value = item.get("label")
    if not isinstance(label_value, str) or not label_value.strip():
        problems.append(_problem(f"{path}.label", "must be a non-empty string", item, key="label"))
        return None
    return label_value.strip()


def _validate_required_amount(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> int | None:
    """Validate a required non-negative amount field."""
    amount_value = item.get("amount")
    if amount_value is None:
        problems.append(_problem(f"{path}.amount", "missing required key", item))
        return None
    if not _is_non_negative_int(amount_value):
        problems.append(
            _problem(f"{path}.amount", "must be a non-negative integer", item, key="amount")
        )
        return None
    return int(amount_value)


def _validate_frequency(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> str | None:
    """Validate a recurring frequency field."""
    frequency_value = item.get("frequency", "monthly")
    if not isinstance(frequency_value, str) or frequency_value not in RECURRING_SAVINGS_FREQUENCIES:
        accepted = ", ".join(sorted(RECURRING_SAVINGS_FREQUENCIES))
        problems.append(
            _problem(
                f"{path}.frequency",
                f"must be one of: {accepted}",
                item,
                key="frequency",
            )
        )
        return None
    return frequency_value


def _validate_optional_non_negative_int(
    item: dict[Any, Any],
    key: str,
    path: str,
    problems: ValidationProblems,
) -> int | None:
    """Validate an optional non-negative integer field."""
    value = item.get(key)
    if value is None:
        return None
    if not _is_non_negative_int(value):
        problems.append(_problem(f"{path}.{key}", "must be a non-negative integer", item, key=key))
        return None
    return int(value)


def _validate_optional_positive_int(
    item: dict[Any, Any],
    key: str,
    path: str,
    problems: ValidationProblems,
) -> int | None:
    """Validate an optional positive integer field."""
    value = item.get(key)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        problems.append(_problem(f"{path}.{key}", "must be a positive integer", item, key=key))
        return None
    return int(value)


def _validate_optional_string(
    item: dict[Any, Any],
    key: str,
    path: str,
    problems: ValidationProblems,
) -> str | None:
    """Validate an optional string field."""
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(_problem(f"{path}.{key}", "must be a string", item, key=key))
        return None
    return value


def _validate_optional_tags(
    value: Any,
    path: str,
    item: dict[Any, Any],
    problems: ValidationProblems,
) -> list[str]:
    """Validate optional recurring_savings tags while deduplicating them."""
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(_problem(path, "must be a list of non-empty strings", item, key="tags"))
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for index, tag in enumerate(value):
        if not isinstance(tag, str) or not tag.strip():
            problems.append(
                _problem(
                    f"{path}[{index}]",
                    "must be a non-empty string",
                    value,
                    key=index,
                )
            )
            continue
        normalized = tag.strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        tags.append(normalized)
    return tags
