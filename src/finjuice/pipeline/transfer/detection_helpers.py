"""
Pairing-scoring helpers for transfer detection.

This module owns the deterministic ordering and opposite-sign pair scoring
helpers used by :mod:`finjuice.pipeline.transfer.detection`, which re-exports
them so existing callers can keep importing from the original module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finjuice.pipeline.transfer.detection import TransferCandidate

CandidateOrderKey = tuple[datetime, int, float, str, str, str, str, str, int]
PairOrderKey = tuple[float, float, datetime, datetime, CandidateOrderKey, CandidateOrderKey]


@dataclass(frozen=True)
class _TransferPairCandidate:
    """A valid opposite-sign transfer pair candidate."""

    outgoing: TransferCandidate
    incoming: TransferCandidate
    time_diff_minutes: float
    amount_ratio: float


def _sign_rank(amount: float) -> int:
    """Return a stable rank for sign-only tie-breaking."""
    if amount < 0:
        return 0
    if amount > 0:
        return 1
    return 2


def _candidate_order_key(tx: TransferCandidate) -> CandidateOrderKey:
    """Return a total order key that does not depend on input row position."""
    return (
        tx.datetime,
        _sign_rank(tx.amount),
        abs(tx.amount),
        tx.currency,
        tx.major_category,
        tx.account,
        tx.counterparty,
        tx.row_hash or f"NOHASH:{tx.id}",
        tx.id,
    )


def _pair_order_key(pair: _TransferPairCandidate) -> PairOrderKey:
    """
    Sort valid pair candidates by accuracy first, then deterministic tie-breakers.

    Tie-breaking is intentionally total and input-order independent:
    1. smaller amount mismatch ratio (exact KRW amount matches win)
    2. smaller timestamp distance inside the configured window
    3. earlier chronological pair span for equally close before/after candidates
    4. stable outgoing/incoming transaction keys, primarily row_hash

    Account and counterparty names are not used as matching constraints because
    Banksalad exports are not consistent enough for that. If two same-category,
    same-currency, opposite-sign rows remain indistinguishable after amount and
    time scoring, row_hash provides a deterministic final choice.
    """
    first_datetime = min(pair.outgoing.datetime, pair.incoming.datetime)
    second_datetime = max(pair.outgoing.datetime, pair.incoming.datetime)
    return (
        pair.amount_ratio,
        pair.time_diff_minutes,
        first_datetime,
        second_datetime,
        _candidate_order_key(pair.outgoing),
        _candidate_order_key(pair.incoming),
    )


def _build_pair_candidate(
    tx_left: TransferCandidate,
    tx_right: TransferCandidate,
    time_diff_minutes: float,
    amount_tolerance: float,
) -> _TransferPairCandidate | None:
    """Return a valid pair candidate for opposite-sign transfers, if any."""
    if tx_left.amount < 0 and tx_right.amount > 0:
        outgoing = tx_left
        incoming = tx_right
    elif tx_right.amount < 0 and tx_left.amount > 0:
        outgoing = tx_right
        incoming = tx_left
    else:
        return None

    if outgoing.currency != incoming.currency:
        return None

    amount_diff = abs(abs(outgoing.amount) - abs(incoming.amount))
    amount_ratio = amount_diff / max(abs(outgoing.amount), abs(incoming.amount))
    if amount_ratio > amount_tolerance:
        return None

    return _TransferPairCandidate(
        outgoing=outgoing,
        incoming=incoming,
        time_diff_minutes=time_diff_minutes,
        amount_ratio=amount_ratio,
    )
