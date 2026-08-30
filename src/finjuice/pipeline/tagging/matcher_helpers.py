"""Leaf numeric/text condition helpers for the tagging matcher.

Extracted from ``tagging/matcher.py`` as the leaf condition-evaluation half of
the matcher. The matcher re-exports these names for backwards compatibility.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from finjuice.pipeline.tagging.models import (
    Condition as _Condition,
)
from finjuice.pipeline.tagging.validator import _parse_between_range

logger = logging.getLogger(__name__)


def _check_numeric_condition(field_value: Any, condition: _Condition) -> bool:
    """Evaluate numeric conditions against amount-like values."""
    if field_value is None:
        return False
    try:
        num = float(field_value)
    except (TypeError, ValueError):
        return False
    if condition.op == "less_than":
        return _check_less_than(num, condition.value)
    if condition.op == "greater_than":
        return _check_greater_than(num, condition.value)
    minimum, maximum = _parse_between_range(condition.value)
    return minimum is not None and maximum is not None and minimum <= num <= maximum


def _check_less_than(num: float, value: str) -> bool:
    """Evaluate a less-than condition safely."""
    try:
        return num < float(value)
    except (TypeError, ValueError):
        return False


def _check_greater_than(num: float, value: str) -> bool:
    """Evaluate a greater-than condition safely."""
    try:
        return num > float(value)
    except (TypeError, ValueError):
        return False


def _check_regex(pattern: str, text: str, field: str) -> bool:
    """Evaluate a regex condition, logging invalid patterns."""
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        logger.warning("Invalid regex for field '%s': %s", field, pattern)
        return False
