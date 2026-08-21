"""Small value-coercion helpers shared by checkup collectors."""

from __future__ import annotations

from typing import Any


def string_or_none(value: Any) -> str | None:
    """Return a string value or None."""
    if value is None:
        return None
    return str(value)


def float_or_none(value: Any) -> float | None:
    """Return a float value or None."""
    if value is None:
        return None
    return float(value)


def merge_warning(left: str | None, right: str | None) -> str | None:
    """Merge two warning strings into one stable sentence."""
    if left and right:
        return f"{left} {right}"
    return left or right
