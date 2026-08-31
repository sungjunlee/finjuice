"""Date and month range helpers for goals.yaml field validation.

Owns optional YYYY-MM / YYYY-MM-DD fields and start/end range checks.
Scalar field checks stay in
:mod:`finjuice.pipeline.goals_validators.fields`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.goals_validators.fields_helpers import _problem
from finjuice.pipeline.goals_validators.models import (
    DATE_LITERAL_PATTERN,
    MONTH_LITERAL_PATTERN,
    ValidationProblems,
)


def _validate_month_range(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> tuple[str | None, str | None]:
    """Validate optional start_month/end_month fields."""
    start_month = _validate_optional_month(item, "start_month", path, problems)
    end_month = _validate_optional_month(item, "end_month", path, problems)
    if start_month is not None and end_month is not None and end_month < start_month:
        problems.append(
            _problem(
                f"{path}.end_month",
                "must be the same as or after start_month",
                item,
                key="end_month",
            )
        )
    return start_month, end_month


def _validate_date_range(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> tuple[str | None, str | None]:
    """Validate optional start_date/end_date fields."""
    start_date = _validate_optional_date(item, "start_date", path, problems)
    end_date = _validate_optional_date(item, "end_date", path, problems)
    if start_date is not None and end_date is not None and end_date < start_date:
        problems.append(
            _problem(
                f"{path}.end_date",
                "must be the same as or after start_date",
                item,
                key="end_date",
            )
        )
    return start_date, end_date


def _validate_optional_month(
    item: dict[Any, Any],
    key: str,
    path: str,
    problems: ValidationProblems,
) -> str | None:
    """Validate an optional YYYY-MM field from a recurring_savings entry."""
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not MONTH_LITERAL_PATTERN.match(value):
        problems.append(_problem(f"{path}.{key}", "must use YYYY-MM format", item, key=key))
        return None
    return value


def _validate_optional_date(
    item: dict[Any, Any],
    key: str,
    path: str,
    problems: ValidationProblems,
) -> str | None:
    """Validate an optional YYYY-MM-DD field from a recurring_savings entry."""
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_LITERAL_PATTERN.match(value):
        problems.append(_problem(f"{path}.{key}", "must use YYYY-MM-DD format", item, key=key))
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        problems.append(
            _problem(
                f"{path}.{key}",
                "must be a real calendar date in YYYY-MM-DD format",
                item,
                key=key,
            )
        )
        return None
    return value
