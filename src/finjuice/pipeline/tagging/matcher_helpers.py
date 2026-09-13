"""Leaf numeric/text condition helpers for the tagging matcher.

Extracted from ``tagging/matcher.py`` as the leaf condition-evaluation half of
the matcher. The matcher re-exports these names for backwards compatibility.
"""

from __future__ import annotations

import logging
import math
import re
from decimal import Decimal
from typing import Any

from finjuice.pipeline.tagging.models import (
    Condition as _Condition,
)
from finjuice.pipeline.tagging.validator import _parse_between_range
from finjuice.pipeline.tagging.validator_schema import _parse_exact_decimal

logger = logging.getLogger(__name__)


def _to_exact_decimal(value: object) -> Decimal | None:
    """Normalize a field or threshold to a finite Decimal, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return _decimal_from_finite_float(value)
    if isinstance(value, str):
        return _parse_exact_decimal(value)
    return None


def _decimal_from_finite_float(value: float) -> Decimal | None:
    """Interpret a legacy float through its visible str representation."""
    if not math.isfinite(value):
        return None
    return _parse_exact_decimal(str(value))


def _check_numeric_condition(field_value: Any, condition: _Condition) -> bool:
    """Evaluate numeric conditions against amount-like values."""
    num = _to_exact_decimal(field_value)
    if num is None:
        return False
    if condition.op == "less_than":
        return _check_less_than(num, condition.value)
    if condition.op == "greater_than":
        return _check_greater_than(num, condition.value)
    minimum, maximum = _parse_between_range(condition.value)
    return minimum is not None and maximum is not None and minimum <= num <= maximum


def _check_less_than(num: object, value: object) -> bool:
    """Evaluate a less-than condition safely."""
    left = _to_exact_decimal(num)
    right = _to_exact_decimal(value)
    return left is not None and right is not None and left < right


def _check_greater_than(num: object, value: object) -> bool:
    """Evaluate a greater-than condition safely."""
    left = _to_exact_decimal(num)
    right = _to_exact_decimal(value)
    return left is not None and right is not None and left > right


def _check_regex(pattern: str, text: str, field: str) -> bool:
    """Evaluate a regex condition, logging invalid patterns."""
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        logger.warning("Invalid regex for field '%s': %s", field, pattern)
        return False
