"""Exact base-10 values for authoritative money, quantity, and rate fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, Literal

from finjuice.pipeline.storage.sqlite.errors import ExactValueError

ValueKind = Literal["money", "quantity", "rate", "number"]
OriginKind = Literal["source", "migration", "calculated"]


class CurrencyState(Enum):
    """Explicit non-code currency states accepted by exact money factories."""

    UNKNOWN = "unknown"


UNKNOWN_CURRENCY: Final = CurrencyState.UNKNOWN

_COEFFICIENT_RE: Final = re.compile(r"^(?:0|-[1-9][0-9]*|[1-9][0-9]*)$")
_CURRENCY_RE: Final = re.compile(r"^[A-Z]{3}$")
_UNIT_RE: Final = re.compile(r"^[a-z][a-z0-9_.-]*\.v[1-9][0-9]*$")
MAX_COEFFICIENT_DIGITS: Final = 100_000


@dataclass(frozen=True)
class ExactValue:
    """Canonical decimal coefficient/scale plus explicit semantic unit."""

    coefficient: str
    scale: int
    lexical: str | None
    value_kind: ValueKind
    origin_kind: OriginKind
    currency: str | None = None
    currency_unknown: bool = False
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.value_kind not in {"money", "quantity", "rate", "number"}:
            raise ExactValueError("Exact value kind is unsupported.")
        if self.origin_kind not in {"source", "migration", "calculated"}:
            raise ExactValueError("Exact value origin is unsupported.")
        if _COEFFICIENT_RE.fullmatch(self.coefficient) is None:
            raise ExactValueError("Coefficient is not canonical signed base-10 text.")
        if len(self.coefficient.removeprefix("-")) > MAX_COEFFICIENT_DIGITS:
            raise ExactValueError("Coefficient exceeds the supported typed digit bound.")
        if isinstance(self.scale, bool) or not isinstance(self.scale, int):
            raise ExactValueError("Scale must be an integer.")
        if not 0 <= self.scale <= 255:
            raise ExactValueError("Scale must be between 0 and 255.")
        if self.origin_kind in {"source", "migration"} and self.lexical is None:
            raise ExactValueError("Source and migration values require exact lexical evidence.")
        if self.lexical is not None:
            lexical_coefficient, lexical_scale = _coefficient_scale_from_lexical(self.lexical)
            if (self.coefficient, self.scale) != (lexical_coefficient, lexical_scale):
                raise ExactValueError("Lexical evidence disagrees with coefficient and scale.")
        self._validate_unit()

    def _validate_unit(self) -> None:
        if self.value_kind == "money":
            known_currency = self.currency is not None
            if known_currency == self.currency_unknown:
                raise ExactValueError("Money requires one known currency or currency_unknown.")
            if self.currency is not None and _CURRENCY_RE.fullmatch(self.currency) is None:
                raise ExactValueError("Currency must be an uppercase three-letter code.")
            if self.unit is not None:
                raise ExactValueError("Money uses currency rather than a domain unit.")
            return
        if self.currency is not None or self.currency_unknown:
            raise ExactValueError("Non-money values cannot carry currency state.")
        if self.unit is None or _UNIT_RE.fullmatch(self.unit) is None:
            raise ExactValueError("Non-money values require a versioned domain unit.")

    @classmethod
    def from_lexical(
        cls,
        lexical: str,
        *,
        value_kind: ValueKind,
        origin_kind: OriginKind = "source",
        currency: str | CurrencyState | None = None,
        unit: str | None = None,
    ) -> "ExactValue":
        """Parse source text without float conversion or decimal-context arithmetic."""
        if not isinstance(lexical, str):
            raise ExactValueError("Authoritative source values must be parsed from text.")
        coefficient, scale = _coefficient_scale_from_lexical(lexical)
        currency_unknown = currency is CurrencyState.UNKNOWN
        currency_code = currency if isinstance(currency, str) else None
        return cls(
            coefficient=coefficient,
            scale=scale,
            lexical=lexical,
            value_kind=value_kind,
            origin_kind=origin_kind,
            currency=currency_code,
            currency_unknown=currency_unknown,
            unit=unit,
        )

    def to_decimal(self) -> Decimal:
        """Reconstruct the exact value without applying the ambient context."""
        negative = self.coefficient.startswith("-")
        digits_text = self.coefficient.removeprefix("-")
        digits = tuple(int(character) for character in digits_text)
        return Decimal((1 if negative else 0, digits, -self.scale))


def _coefficient_scale_from_lexical(lexical: str) -> tuple[str, int]:
    if not isinstance(lexical, str):
        raise ExactValueError("Authoritative source values must be parsed from text.")
    try:
        parsed = Decimal(lexical)
    except Exception as exc:
        raise ExactValueError("Lexical value is not a base-10 decimal.") from exc
    if not parsed.is_finite():
        raise ExactValueError("NaN and infinity are not authoritative decimal values.")

    sign, digits, exponent = parsed.as_tuple()
    if not isinstance(exponent, int):
        raise ExactValueError("Lexical value has a non-finite exponent.")
    coefficient_digits = "".join(str(digit) for digit in digits).lstrip("0") or "0"
    if coefficient_digits == "0":
        scale = max(-exponent, 0)
    elif exponent > 0:
        if len(coefficient_digits) + exponent > MAX_COEFFICIENT_DIGITS:
            raise ExactValueError(
                "Coefficient exceeds the supported typed digit bound; "
                "preserve it as opaque evidence."
            )
        coefficient_digits += "0" * exponent
        scale = 0
    else:
        scale = -exponent
    coefficient = coefficient_digits
    if sign and coefficient_digits != "0":
        coefficient = f"-{coefficient_digits}"
    return coefficient, scale
