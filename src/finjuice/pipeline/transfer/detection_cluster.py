"""
Candidate-pairing cluster for transfer detection.

This module owns :func:`detect_transfer_pairs`, the deterministic scored greedy
matcher over :class:`TransferCandidate` rows. CSV partition orchestration stays
in :mod:`finjuice.pipeline.transfer.detection`, which re-exports this function
so existing callers can keep importing from the original module.
"""

import logging
from typing import Dict, List, Set

from finjuice.pipeline.constants import (
    DEFAULT_TRANSFER_AMOUNT_TOLERANCE,
    DEFAULT_TRANSFER_TIME_WINDOW_MINUTES,
)
from finjuice.pipeline.transfer.detection_candidates import TransferCandidate
from finjuice.pipeline.transfer.detection_helpers import (
    _build_pair_candidate,
    _candidate_order_key,
    _pair_order_key,
    _TransferPairCandidate,
)

logger = logging.getLogger(__name__)


def detect_transfer_pairs(
    transactions: List[TransferCandidate],
    time_window_minutes: int = DEFAULT_TRANSFER_TIME_WINDOW_MINUTES,
    amount_tolerance: float = DEFAULT_TRANSFER_AMOUNT_TOLERANCE,
) -> Dict[str, List[int]]:
    """
    Detect internal transfer pairs using deterministic scored greedy matching.

    Matching rules:
    1. Group by major_category (e.g., '내계좌이체' only pairs with '내계좌이체')
    2. Match criteria (all must be true):
       - Same currency
       - Same abs(amount) within tolerance
       - Opposite signs (one negative, one positive)
       - Time difference ≤ time_window_minutes
    3. Build every valid pair in both timestamp directions, then greedily accept
       candidates in a deterministic total order: closest amount ratio, closest
       timestamp distance, earliest chronological span, then row_hash-backed
       transaction keys. Once a row is paired, it cannot be paired again.

    Args:
        transactions: List of transfer candidates
        time_window_minutes: Max time difference for pairing
            (default: DEFAULT_TRANSFER_TIME_WINDOW_MINUTES = 5 minutes)
        amount_tolerance: Relative tolerance for amount matching
            (default: DEFAULT_TRANSFER_AMOUNT_TOLERANCE = 1%)

            See: finjuice.pipeline.constants for rationale and tuning guidance.

    Returns:
        Dict mapping transfer_group_id → [transaction_ids]

    Example:
        >>> candidates = [
        ...     TransferCandidate(1, datetime(2025,1,15,14,30), -50000, "신한카드",
        ...                       "내계좌이체", "내계좌이체", "KRW", "abc12345"),
        ...     TransferCandidate(2, datetime(2025,1,15,14,31), 50000, "우리은행",
        ...                       "내계좌이체", "내계좌이체", "KRW", "def67890"),
        ... ]
        >>> pairs = detect_transfer_pairs(candidates)
        >>> pairs
        {'T_abc12345_def67890': [1, 2]}
    """
    # Group by major_category
    transfers_by_category: Dict[str, List[TransferCandidate]] = {}
    for tx in transactions:
        if tx.major_category not in transfers_by_category:
            transfers_by_category[tx.major_category] = []
        transfers_by_category[tx.major_category].append(tx)

    transfer_groups: Dict[str, List[int]] = {}

    # Process each category separately in lexical order so fallback IDs and
    # collision suffixes remain deterministic across input row ordering.
    for category in sorted(transfers_by_category):
        txs = sorted(transfers_by_category[category], key=_candidate_order_key)
        matched_ids: Set[int] = set()
        pair_candidates: List[_TransferPairCandidate] = []

        for i, tx_left in enumerate(txs):
            for tx_right in txs[i + 1 :]:
                time_diff = (tx_right.datetime - tx_left.datetime).total_seconds() / 60
                if time_diff > time_window_minutes:
                    break  # Sorted by time, no later row can be within the window.

                pair_candidate = _build_pair_candidate(
                    tx_left=tx_left,
                    tx_right=tx_right,
                    time_diff_minutes=time_diff,
                    amount_tolerance=amount_tolerance,
                )
                if pair_candidate is not None:
                    pair_candidates.append(pair_candidate)

        for pair_candidate in sorted(pair_candidates, key=_pair_order_key):
            tx_from = pair_candidate.outgoing
            tx_to = pair_candidate.incoming
            if tx_from.id in matched_ids or tx_to.id in matched_ids:
                continue

            # Generate deterministic group_id from sorted row_hashes
            if not tx_from.row_hash or not tx_to.row_hash:
                # Schema violation: row_hash is required but missing
                logger.error(
                    f"DATA INTEGRITY: row_hash missing in transfer pair - "
                    f"from_id={tx_from.id} (hash='{tx_from.row_hash}'), "
                    f"to_id={tx_to.id} (hash='{tx_to.row_hash}'). "
                    f"This may indicate ingest issues. Using fallback group_id."
                )
                group_id = f"T_NOHASH_{len(transfer_groups):04d}"
            else:
                sorted_hashes = sorted([tx_from.row_hash, tx_to.row_hash])
                group_id = f"T_{sorted_hashes[0][:8]}_{sorted_hashes[1][:8]}"

            # Check for collision (unlikely but possible with hash truncation)
            if group_id in transfer_groups:
                logger.error(
                    f"UNEXPECTED: Group ID collision '{group_id}' - "
                    f"existing pair: {transfer_groups[group_id]}, "
                    f"new pair: [{tx_from.id}, {tx_to.id}]. "
                    f"May indicate duplicate data. Adding suffix."
                )
                group_id = f"{group_id}_{len(transfer_groups)}"

            transfer_groups[group_id] = [tx_from.id, tx_to.id]
            matched_ids.add(tx_from.id)
            matched_ids.add(tx_to.id)
            logger.debug(
                f"Paired transfer {group_id}: "
                f"matched 2 transactions (time_diff={pair_candidate.time_diff_minutes:.1f}min, "
                f"amount_ratio={pair_candidate.amount_ratio:.3f})"
            )

    return transfer_groups
