"""Exact decimal helpers for asset observation amounts."""

from __future__ import annotations

from decimal import Decimal

from finjuice.pipeline.assets.models import FxBasis, Measure, MoneyAmount
from finjuice.pipeline.storage.sqlite.exact import ExactValue


def parse_decimal(value: object) -> Decimal:
    """Parse an exact decimal from int/str/Decimal. Reject floats."""
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError(
            "Asset amounts must be exact decimals from int, str, or Decimal, not float."
        )
    return ExactValue.from_lexical(
        str(Decimal(value)) if isinstance(value, int) else str(value),
        value_kind="number",
        unit="asset.value.v1",
    ).to_decimal()


def _parts(value: Decimal) -> tuple[int, int]:
    exact = parse_decimal(value)
    sign, digits, exponent = exact.as_tuple()
    assert isinstance(exponent, int)
    # Decimal-to-int conversion avoids Python's decimal-text integer digit limit.
    return int(Decimal((sign, digits, 0))), -exponent


def _result(coefficient: int, scale: int) -> Decimal:
    return ExactValue(
        coefficient=format(Decimal(coefficient), "f"),
        scale=scale,
        lexical=None,
        value_kind="number",
        origin_kind="calculated",
        unit="asset.value.v1",
    ).to_decimal()


def exact_add(left: Decimal, right: Decimal) -> Decimal:
    """Add finite typed decimals without ambient precision or rounding."""
    left_int, left_scale = _parts(left)
    right_int, right_scale = _parts(right)
    scale = max(left_scale, right_scale)
    return _result(
        left_int * 10 ** (scale - left_scale) + right_int * 10 ** (scale - right_scale),
        scale,
    )


def exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    """Subtract finite typed decimals without ambient precision or rounding."""
    return exact_add(left, parse_decimal(right).copy_negate())


def exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    """Multiply finite typed decimals; reject results outside ExactValue bounds."""
    left_int, left_scale = _parts(left)
    right_int, right_scale = _parts(right)
    return _result(left_int * right_int, left_scale + right_scale)


def valued_amount(measure: Measure, valuation_currency: str) -> MoneyAmount | None:
    """Convert a measure into the query valuation currency when an FX basis exists."""
    original = measure.amount
    if original is None:
        return None
    if original.currency == valuation_currency:
        return MoneyAmount(amount=parse_decimal(original.amount), currency=valuation_currency)
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
    return MoneyAmount(amount=exact_multiply(original.amount, fx.rate), currency=valuation_currency)
