"""Bounded, context-independent exact calculation for canonical reconciliation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)

from finjuice.pipeline.reconcile.engine import (
    DEFAULT_WINDOW_DAYS,
    reconcile,
    reconciliation_work_meter,
)
from finjuice.pipeline.reconcile.models import EvidenceItem, PaymentItem, ReconcileReport
from finjuice.pipeline.storage.sqlite.exact import MAX_COEFFICIENT_DIGITS

MAX_INPUT_ITEMS = 10_000
MAX_TOTAL_DIGITS = 1_000_000
MAX_CANDIDATE_PAIRS = 1_000_000
MAX_WORK_UNITS = 1_000_000
MAX_DIGIT_WORK = 20_000_000
_ERROR = "Canonical reconciliation exceeds supported exact input or calculation limits."


def reconcile_exact(
    evidence: Sequence[EvidenceItem],
    payments: Sequence[PaymentItem],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> ReconcileReport:
    """Run the existing matcher with exact arithmetic and explicit resource bounds."""
    try:
        if len(evidence) + len(payments) > MAX_INPUT_ITEMS:
            raise ValueError(_ERROR)
        evidence, payments = tuple(evidence), tuple(payments)
        precision = _precision(evidence, payments)
        pairs = len(evidence) * len(payments)
        if pairs > MAX_CANDIDATE_PAIRS or type(window_days) is not int or window_days < 0:
            raise ValueError(_ERROR)
        meter = _ActualWork(precision)
        with (
            localcontext(_context(precision)),
            reconciliation_work_meter(meter.charge, exact_bounds=True),
        ):
            return reconcile(evidence, payments, window_days=window_days)
    except (ArithmeticError, ValueError, TypeError):
        raise ValueError(_ERROR) from None


def calculation_limits() -> dict[str, int]:
    """Return independent public limits; digit-work is a conservative work proxy."""
    return {
        "max_input_items": MAX_INPUT_ITEMS,
        "max_total_digits": MAX_TOTAL_DIGITS,
        "max_candidate_pairs": MAX_CANDIDATE_PAIRS,
        "max_work_units": MAX_WORK_UNITS,
        "max_digit_work": MAX_DIGIT_WORK,
        "max_coefficient_digits": MAX_COEFFICIENT_DIGITS,
        "max_scale": 255,
    }


def _context(precision: int) -> Context:
    return Context(
        prec=precision,
        rounding=ROUND_HALF_EVEN,
        Emax=999999,
        Emin=-999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded],
    )


def _precision(evidence: Sequence[EvidenceItem], payments: Sequence[PaymentItem]) -> int:
    if len(evidence) + len(payments) > MAX_INPUT_ITEMS:
        raise ValueError(_ERROR)
    operands = [_operand(item.amount) for item in evidence]
    operands.extend(_operand(item.amount) for item in payments)
    if sum(digits for digits, _ in operands) > MAX_TOTAL_DIGITS:
        raise ValueError(_ERROR)
    scale = max((max(0, -exponent) for _, exponent in operands), default=0)
    width = max((digits + exponent + scale for digits, exponent in operands), default=1)
    # At most five aligned amounts are summed, and the partial threshold is 0.5.
    # One carry digit covers those sums, residuals, and the half-amount product.
    return max(1, width) + 1


def _operand(value: Decimal) -> tuple[int, int]:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(_ERROR)
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        raise ValueError(_ERROR)
    digits = len(parts.digits)
    if exponent < -255 or digits + max(0, exponent) > MAX_COEFFICIENT_DIGITS:
        raise ValueError(_ERROR)
    return digits, exponent


@dataclass
class _ActualWork:
    precision: int
    units: int = 0

    def charge(self, units: int) -> None:
        self.units += units
        if self.units > MAX_WORK_UNITS or self.units * self.precision > MAX_DIGIT_WORK:
            raise ValueError(_ERROR)
