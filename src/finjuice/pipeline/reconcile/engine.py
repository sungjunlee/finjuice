"""N:M evidence matching that keeps unmatched rows when the ledger is empty."""

from __future__ import annotations

from collections.abc import Sequence

from finjuice.pipeline.reconcile.decisions import (  # noqa: F401
    confirm_match,
    withdraw_match,
)
from finjuice.pipeline.reconcile.models import (
    EVIDENCE_SOURCE_KINDS,
    LEDGER_SOURCE_KINDS,
    EvidenceItem,
    MatchGroup,
    PaymentItem,
    ReconcileReport,
)
from finjuice.pipeline.reconcile.nm import (  # noqa: F401
    _best_partial,
    _charge_work,
    _combo_candidates,
    _combo_summing_to,
    _eligible_exact_evidence,
    _evidence_summing_to,
    _in_window,
    _match_many_to_one,
    _match_one_to_many,
    _match_one_to_one,
    _metered_combinations,
    _possible_evidence_sizes,
    _possible_payment_sizes,
    _unmatched_evidence,
)
from finjuice.pipeline.reconcile.nm import money_abs as money_abs
from finjuice.pipeline.reconcile.nm import reconciliation_work_meter as reconciliation_work_meter

DEFAULT_WINDOW_DAYS = 14


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


def _group_sort_key(group: MatchGroup) -> tuple[str, str]:
    evidence_key = ",".join(group.evidence_ids)
    payment_key = ",".join(group.payment_ids)
    return (evidence_key, payment_key)
