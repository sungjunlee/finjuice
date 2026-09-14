"""N:M candidate matching for purchase/order evidence vs ledger payments."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from itertools import combinations
from math import gcd
from typing import TypeVar

from finjuice.pipeline.reconcile.models import EvidenceItem, MatchGroup, PaymentItem
from finjuice.pipeline.reconcile.money import money_abs as _exact_money_abs

_MAX_COMBO = 5
_MAX_CANDIDATES = 16
_MIN_PARTIAL_COVERAGE = Decimal("0.5")
_ZERO = Decimal("0")


_WorkItem = TypeVar("_WorkItem")
_WORK_METER: ContextVar[Callable[[int], None] | None] = ContextVar(
    "reconcile_work_meter", default=None
)


_EXACT_BOUNDS: ContextVar[bool] = ContextVar("reconcile_exact_bounds", default=False)


@contextmanager
def reconciliation_work_meter(
    charge: Callable[[int], None], *, exact_bounds: bool = False
) -> Iterator[None]:
    """Scope an optional actual-work meter without changing legacy matching."""
    token = _WORK_METER.set(charge)
    bounds_token = _EXACT_BOUNDS.set(exact_bounds)
    try:
        yield
    finally:
        _EXACT_BOUNDS.reset(bounds_token)
        _WORK_METER.reset(token)


def _charge_work(units: int = 1) -> None:
    meter = _WORK_METER.get()
    if meter is not None:
        meter(units)


def money_abs(value: Decimal) -> Decimal:
    """Meter actual amount comparisons while retaining the existing arithmetic."""
    _charge_work()
    return _exact_money_abs(value)


def _metered_combinations(items: Sequence[_WorkItem], size: int) -> Iterator[tuple[_WorkItem, ...]]:
    for combo in combinations(items, size):
        _charge_work(size)
        yield combo


def _in_window(left: EvidenceItem, right: PaymentItem, window_days: int) -> bool:
    _charge_work()
    return (
        left.currency == right.currency
        and abs((left.occurred_on - right.occurred_on).days) <= window_days
    )


def _match_one_to_one(
    evidence: Sequence[EvidenceItem],
    payments: Sequence[PaymentItem],
    window_days: int,
    used_evidence: set[str],
    used_payments: set[str],
) -> list[MatchGroup]:
    groups: list[MatchGroup] = []
    for item in evidence:
        if item.evidence_id in used_evidence:
            continue
        matches = [
            payment
            for payment in payments
            if payment.payment_id not in used_payments
            and _in_window(item, payment, window_days)
            and money_abs(payment.amount) == money_abs(item.amount)
        ]
        matches.sort(key=lambda payment: (payment.occurred_on, payment.payment_id))
        if not matches:
            continue
        payment = matches[0]
        reason = "refund_or_inflow" if payment.amount > _ZERO else "exact_one_to_one"
        groups.append(
            MatchGroup(
                evidence_ids=(item.evidence_id,),
                payment_ids=(payment.payment_id,),
                status="matched",
                residual=_ZERO,
                reason=reason,
            )
        )
        used_evidence.add(item.evidence_id)
        used_payments.add(payment.payment_id)
    return groups


def _match_one_to_many(
    evidence: Sequence[EvidenceItem],
    payments: Sequence[PaymentItem],
    window_days: int,
    used_evidence: set[str],
    used_payments: set[str],
) -> list[MatchGroup]:
    groups: list[MatchGroup] = []
    for item in evidence:
        if item.evidence_id in used_evidence:
            continue
        candidates = _combo_candidates(
            [
                payment
                for payment in payments
                if payment.payment_id not in used_payments
                and _in_window(item, payment, window_days)
                and payment.amount <= _ZERO
            ],
            money_abs(item.amount),
        )
        combo = _combo_summing_to(candidates, money_abs(item.amount))
        if combo is None:
            partial = _best_partial(candidates, money_abs(item.amount))
            if partial is None:
                continue
            allocated = sum((money_abs(payment.amount) for payment in partial), _ZERO)
            groups.append(
                MatchGroup(
                    evidence_ids=(item.evidence_id,),
                    payment_ids=tuple(payment.payment_id for payment in partial),
                    status="partial",
                    residual=money_abs(item.amount) - allocated,
                    reason="installment_partial",
                )
            )
            used_evidence.add(item.evidence_id)
            used_payments.update(payment.payment_id for payment in partial)
            continue
        groups.append(
            MatchGroup(
                evidence_ids=(item.evidence_id,),
                payment_ids=tuple(payment.payment_id for payment in combo),
                status="matched",
                residual=_ZERO,
                reason="installment_one_to_many",
            )
        )
        used_evidence.add(item.evidence_id)
        used_payments.update(payment.payment_id for payment in combo)
    return groups


def _match_many_to_one(
    evidence: Sequence[EvidenceItem],
    payments: Sequence[PaymentItem],
    window_days: int,
    used_evidence: set[str],
    used_payments: set[str],
) -> list[MatchGroup]:
    groups: list[MatchGroup] = []
    pending = [item for item in evidence if item.evidence_id not in used_evidence]
    for payment in payments:
        if payment.payment_id in used_payments:
            continue
        candidates = [
            item
            for item in pending
            if item.evidence_id not in used_evidence and _in_window(item, payment, window_days)
        ]
        combo = _evidence_summing_to(candidates, money_abs(payment.amount))
        if combo is None:
            continue
        groups.append(
            MatchGroup(
                evidence_ids=tuple(item.evidence_id for item in combo),
                payment_ids=(payment.payment_id,),
                status="matched",
                residual=_ZERO,
                reason="orders_many_to_one",
            )
        )
        used_payments.add(payment.payment_id)
        used_evidence.update(item.evidence_id for item in combo)
    return groups


def _unmatched_evidence(
    evidence: Sequence[EvidenceItem], used_evidence: set[str]
) -> list[MatchGroup]:
    groups = [
        MatchGroup(
            evidence_ids=(item.evidence_id,),
            payment_ids=(),
            status="unmatched",
            residual=money_abs(item.amount),
            reason="missing_ledger_coverage",
        )
        for item in evidence
        if item.evidence_id not in used_evidence
    ]
    used_evidence.update(
        item.evidence_id for item in evidence if item.evidence_id not in used_evidence
    )
    return groups


def _combo_candidates(payments: Sequence[PaymentItem], target: Decimal) -> list[PaymentItem]:
    """Keep combo search small; prefer larger in-window amounts under the target."""
    eligible = [payment for payment in payments if money_abs(payment.amount) <= target]
    if len(eligible) <= _MAX_CANDIDATES:
        return eligible
    ordered = sorted(
        eligible,
        key=lambda payment: (
            -money_abs(payment.amount),
            payment.occurred_on,
            payment.payment_id,
        ),
    )
    return ordered[:_MAX_CANDIDATES]


def _combo_summing_to(
    payments: Sequence[PaymentItem], target: Decimal
) -> tuple[PaymentItem, ...] | None:
    ordered = sorted(payments, key=lambda payment: (payment.occurred_on, payment.payment_id))
    limit = min(len(ordered), _MAX_COMBO)
    for size in _possible_payment_sizes(ordered, target, limit, partial=False):
        for combo in _metered_combinations(ordered, size):
            total = sum((money_abs(payment.amount) for payment in combo), _ZERO)
            if total == target:
                return combo
    return None


def _evidence_summing_to(
    items: Sequence[EvidenceItem], target: Decimal
) -> tuple[EvidenceItem, ...] | None:
    ordered = sorted(items, key=lambda item: (item.occurred_on, item.evidence_id))
    if _EXACT_BOUNDS.get():
        ordered = _eligible_exact_evidence(ordered, target)
    limit = min(len(ordered), _MAX_COMBO)
    sizes = _possible_evidence_sizes(ordered, target, limit)
    for size in sizes:
        for combo in _metered_combinations(ordered, size):
            total = sum((money_abs(item.amount) for item in combo), _ZERO)
            if total == target:
                return combo
    return None


def _eligible_exact_evidence(items: Sequence[EvidenceItem], target: Decimal) -> list[EvidenceItem]:
    eligible = [item for item in items if money_abs(item.amount) <= target]
    amounts = [item.amount.copy_abs() for item in eligible]
    exponents = [value.as_tuple().exponent for value in [*amounts, target]]
    scale = max(0, *(-exponent for exponent in exponents if isinstance(exponent, int)))
    unit = 10**scale
    divisor = 0
    for amount in amounts:
        _charge_work()
        numerator, denominator = amount.as_integer_ratio()
        divisor = gcd(divisor, numerator * (unit // denominator))
        if divisor == 1:
            return eligible
    _charge_work()
    numerator, denominator = target.as_integer_ratio()
    target_units = numerator * (unit // denominator)
    possible = target_units == 0 if divisor == 0 else target_units % divisor == 0
    return eligible if possible else []


def _possible_evidence_sizes(
    items: Sequence[EvidenceItem], target: Decimal, limit: int
) -> list[int]:
    sizes = list(range(2, limit + 1))
    if not _EXACT_BOUNDS.get():
        return sizes
    amounts = sorted(money_abs(item.amount) for item in items)
    possible = []
    for size in sizes:
        _charge_work(2 * size)
        if sum(amounts[:size], _ZERO) <= target <= sum(amounts[-size:], _ZERO):
            possible.append(size)
    return possible


def _possible_payment_sizes(
    payments: Sequence[PaymentItem], target: Decimal, limit: int, *, partial: bool
) -> list[int]:
    sizes = list(range(1 if partial else 2, limit + 1))
    if not _EXACT_BOUNDS.get():
        return sizes
    amounts = sorted(money_abs(payment.amount) for payment in payments)
    threshold = _MIN_PARTIAL_COVERAGE * target if partial else target
    possible = []
    for size in sizes:
        _charge_work(2 * size)
        minimum = sum(amounts[:size], _ZERO)
        maximum = sum(amounts[-size:], _ZERO)
        if partial:
            if maximum >= threshold and minimum < target:
                possible.append(size)
        elif minimum <= target <= maximum:
            possible.append(size)
    return possible


def _best_partial(
    payments: Sequence[PaymentItem], target: Decimal
) -> tuple[PaymentItem, ...] | None:
    ordered = sorted(payments, key=lambda payment: (payment.occurred_on, payment.payment_id))
    best: tuple[PaymentItem, ...] | None = None
    best_total = _ZERO
    limit = min(len(ordered), _MAX_COMBO)
    for size in _possible_payment_sizes(ordered, target, limit, partial=True):
        for combo in _metered_combinations(ordered, size):
            total = sum((money_abs(payment.amount) for payment in combo), _ZERO)
            if best_total < total < target:
                best = combo
                best_total = total
    if best is None or best_total < (_MIN_PARTIAL_COVERAGE * target):
        return None
    return best
