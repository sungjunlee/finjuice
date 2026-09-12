"""Exact decimal helpers for reconcile amounts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_money(value: object) -> Decimal:
    """Parse a money amount from int/str/Decimal. Reject floats."""
    if isinstance(value, float):
        raise ValueError("Reconcile amounts must be exact decimals, not float.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Invalid reconcile amount.") from error


def money_abs(value: Decimal) -> Decimal:
    """Return the absolute value of an exact amount."""
    return abs(value)
