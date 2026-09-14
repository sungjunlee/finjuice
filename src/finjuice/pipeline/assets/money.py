"""Exact decimal helpers for asset observation amounts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from finjuice.pipeline.assets.models import FxBasis, Measure, MoneyAmount


def parse_decimal(value: object) -> Decimal:
    """Parse an exact decimal from int/str/Decimal. Reject floats."""
    if isinstance(value, float):
        raise ValueError("Asset amounts must be exact decimals, not float.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Invalid asset decimal amount.") from error


def valued_amount(measure: Measure, valuation_currency: str) -> MoneyAmount | None:
    """Convert a measure into the query valuation currency when an FX basis exists."""
    original = measure.amount
    if original is None:
        return None
    if original.currency == valuation_currency:
        return MoneyAmount(amount=original.amount, currency=valuation_currency)
    converted = _convert(original, measure.fx, valuation_currency)
    return converted


def _convert(
    original: MoneyAmount,
    fx: FxBasis | None,
    valuation_currency: str,
) -> MoneyAmount | None:
    if fx is None:
        return None
    if fx.quote_currency != valuation_currency:
        return None
    return MoneyAmount(amount=original.amount * fx.rate, currency=valuation_currency)
