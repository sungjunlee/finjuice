"""Field-level helpers for goals.yaml validation.

Section validators stay in ``validate.py``. This module owns scalar field
checks, date/month ranges, and problem construction with source locations.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.goals_validators.models import (
    DATE_LITERAL_PATTERN,
    MONTH_LITERAL_PATTERN,
    RECURRING_SAVINGS_FREQUENCIES,
    GoalsValidationProblem,
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


def _problem(
    path: str,
    message: str,
    node: Any,
    *,
    key: str | int | None = None,
) -> GoalsValidationProblem:
    """Create a validation problem with best-effort source location data."""
    line, column = _position(node, key=key)
    return GoalsValidationProblem(path=path, message=message, line=line, column=column)


def _parse_error_problem(exc: Exception) -> GoalsValidationProblem:
    """Convert a YAML parse exception into a line-numbered problem."""
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


def _position(node: Any, *, key: str | int | None = None) -> tuple[int | None, int | None]:
    """Return a 1-based (line, column) tuple for a ruamel node or mapping key."""
    line: int | None = None
    column: int | None = None
    lc = getattr(node, "lc", None)
    if lc is None:
        return None, None

    if key is not None:
        if isinstance(key, int):
            try:
                item_line, item_column = lc.item(key)
            except (IndexError, KeyError, TypeError):
                pass
            else:
                line = item_line + 1
                column = item_column + 1
                return line, column
        try:
            key_line, key_column = lc.key(key)
        except (KeyError, TypeError):
            pass
        else:
            line = key_line + 1
            column = key_column + 1
            return line, column

    raw_line = getattr(lc, "line", None)
    raw_column = getattr(lc, "col", None)
    if isinstance(raw_line, int):
        line = raw_line + 1
    if isinstance(raw_column, int):
        column = raw_column + 1
    return line, column
