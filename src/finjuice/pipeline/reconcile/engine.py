"""N:M evidence matching that keeps unmatched rows when the ledger is empty."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import combinations

from finjuice.pipeline.reconcile.models import (
    EVIDENCE_SOURCE_KINDS,
    LEDGER_SOURCE_KINDS,
    EvidenceItem,
    MatchGroup,
    PaymentItem,
    ReconcileReport,
)
from finjuice.pipeline.reconcile.money import money_abs

DEFAULT_WINDOW_DAYS = 14
_MAX_COMBO = 5
_ZERO = Decimal("0")


def reconcile(
    evidence: Sequence[EvidenceItem],
    payments: Sequence[PaymentItem],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    preserved: Sequence[MatchGroup] = (),
) -> ReconcileReport:
    """Match evidence to payments without deleting unmatched evidence.

    Confirmed/withdrawn groups in *preserved* are kept. Re-running with the
    same ids does not duplicate groups. Email/order evidence cannot be treated
    as ledger payments.
    """
    _validate_evidence(evidence)
    kept = tuple(group for group in preserved if group.decision in {"confirmed", "withdrawn"})
    used_evidence = {item for group in kept for item in group.evidence_ids}
    used_payments = {item for group in kept for item in group.payment_ids}

    pending_evidence = [item for item in evidence if item.evidence_id not in used_evidence]
    pending_payments = [item for item in payments if item.payment_id not in used_payments]

    groups: list[MatchGroup] = list(kept)
    groups.extend(
        _match_one_to_one(
            pending_evidence, pending_payments, window_days, used_evidence, used_payments
        )
    )
    groups.extend(
        _match_one_to_many(
            pending_evidence, pending_payments, window_days, used_evidence, used_payments
        )
    )
    groups.extend(
        _match_many_to_one(
            pending_evidence, pending_payments, window_days, used_evidence, used_payments
        )
    )
    groups.extend(_unmatched_evidence(pending_evidence, used_evidence))
    groups.sort(key=_group_sort_key)
    return ReconcileReport(
        groups=tuple(groups),
        evidence_count=len(evidence),
        payment_count=len(payments),
    )


def _validate_evidence(evidence: Sequence[EvidenceItem]) -> None:
    seen: set[str] = set()
    for item in evidence:
        if item.source_kind in LEDGER_SOURCE_KINDS:
            raise ValueError("Ledger sources cannot be recorded as evidence.")
        if item.source_kind not in EVIDENCE_SOURCE_KINDS:
            raise ValueError("Unknown evidence source_kind.")
        if item.evidence_id in seen:
            raise ValueError("Duplicate evidence_id.")
        seen.add(item.evidence_id)


def _in_window(left: EvidenceItem, right: PaymentItem, window_days: int) -> bool:
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
        candidates = [
            payment
            for payment in payments
            if payment.payment_id not in used_payments
            and _in_window(item, payment, window_days)
            and payment.amount <= _ZERO
        ]
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


def _combo_summing_to(
    payments: Sequence[PaymentItem], target: Decimal
) -> tuple[PaymentItem, ...] | None:
    ordered = sorted(payments, key=lambda payment: (payment.occurred_on, payment.payment_id))
    limit = min(len(ordered), _MAX_COMBO)
    for size in range(2, limit + 1):
        for combo in combinations(ordered, size):
            total = sum((money_abs(payment.amount) for payment in combo), _ZERO)
            if total == target:
                return combo
    return None


def _evidence_summing_to(
    items: Sequence[EvidenceItem], target: Decimal
) -> tuple[EvidenceItem, ...] | None:
    ordered = sorted(items, key=lambda item: (item.occurred_on, item.evidence_id))
    limit = min(len(ordered), _MAX_COMBO)
    for size in range(2, limit + 1):
        for combo in combinations(ordered, size):
            total = sum((money_abs(item.amount) for item in combo), _ZERO)
            if total == target:
                return combo
    return None


def _best_partial(
    payments: Sequence[PaymentItem], target: Decimal
) -> tuple[PaymentItem, ...] | None:
    ordered = sorted(payments, key=lambda payment: (payment.occurred_on, payment.payment_id))
    best: tuple[PaymentItem, ...] | None = None
    best_total = _ZERO
    limit = min(len(ordered), _MAX_COMBO)
    for size in range(1, limit + 1):
        for combo in combinations(ordered, size):
            total = sum((money_abs(payment.amount) for payment in combo), _ZERO)
            if best_total < total < target:
                best = combo
                best_total = total
    return best


def _group_sort_key(group: MatchGroup) -> tuple[str, str]:
    evidence_key = ",".join(group.evidence_ids)
    payment_key = ",".join(group.payment_ids)
    return (evidence_key, payment_key)
