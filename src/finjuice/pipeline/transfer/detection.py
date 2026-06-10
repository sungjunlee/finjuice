"""
Transfer detection and pairing module (Polars-only).

This module implements deterministic transfer pair detection to identify internal
account transfers (e.g., credit card payments, inter-account transfers) and
prevent double-counting in expense reports.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import polars as pl

from finjuice.pipeline.constants import (
    DEFAULT_TRANSFER_AMOUNT_TOLERANCE,
    DEFAULT_TRANSFER_TIME_WINDOW_MINUTES,
)

logger = logging.getLogger(__name__)


@dataclass
class TransferCandidate:
    """A transaction that might be part of a transfer pair."""

    id: int
    datetime: datetime
    amount: float
    account: str
    counterparty: str
    major_category: str
    currency: str
    row_hash: str = ""  # For deterministic sorting/group ID; empty triggers fallback ID


@dataclass(frozen=True)
class _TransferPairCandidate:
    """A valid opposite-sign transfer pair candidate."""

    outgoing: TransferCandidate
    incoming: TransferCandidate
    time_diff_minutes: float
    amount_ratio: float


CandidateOrderKey = tuple[datetime, int, float, str, str, str, str, str, int]
PairOrderKey = tuple[float, float, datetime, datetime, CandidateOrderKey, CandidateOrderKey]


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


def _build_transfer_candidates(df_transfers: pl.DataFrame) -> tuple[list[TransferCandidate], int]:
    """Build valid transfer candidates from transfer-like rows."""
    candidates: list[TransferCandidate] = []
    skipped_count = 0
    for idx, row in enumerate(df_transfers.iter_rows(named=True)):
        dt_str = row.get("datetime")
        try:
            if not dt_str:
                logger.warning(f"Skipping transfer candidate at index {idx}: missing datetime")
                skipped_count += 1
                continue
            dt = datetime.fromisoformat(dt_str)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Skipping transfer candidate at index {idx}: invalid datetime '{dt_str}': {e}"
            )
            skipped_count += 1
            continue

        candidates.append(
            TransferCandidate(
                id=idx,  # Use enumeration index
                datetime=dt,
                amount=float(row.get("amount", 0)),
                account=row.get("account") or "",
                counterparty=row.get("merchant_raw") or "",
                major_category=row.get("major_raw") or "",
                currency=row.get("currency") or "KRW",
                row_hash=row.get("row_hash") or "",
            )
        )

    return candidates, skipped_count


def run_transfer_detection(csv_base_dir: Path) -> Dict[str, int]:
    """
    Main entry point for transfer detection (Polars-only).

    Fetches transfer candidates from CSV partitions, detects pairs, and updates
    is_transfer_candidate, is_transfer, and transfer_group_id fields.

    Args:
        csv_base_dir: Base directory for CSV partitions

    Returns:
        Summary dict with counts:
        {
            'candidate_rows': int,  # Total transfer-like rows
            'candidates': int,  # Valid transfer candidates considered for pairing
            'pairs': int,       # Number of matched pairs
            'paired': int,      # Transactions successfully paired
            'confirmed': int,   # Transactions in confirmed pairs
            'unpaired': int,    # Valid candidates without match
            'unconfirmed_candidates': int,  # Transfer-like rows not in confirmed pairs
            'skipped': int,     # Skipped due to invalid datetime
            'errors': int       # Data integrity errors (missing hash, out-of-bounds)
        }

    Example:
        >>> from pathlib import Path
        >>> result = run_transfer_detection(Path('data/transactions'))
        >>> print(f"Found {result['pairs']} transfer pairs")
    """
    logger.info("Starting transfer detection (Polars backend)")

    from finjuice.pipeline.storage import csv_transactions

    # Load all transactions from CSV partitions (Polars)
    df = csv_transactions.get_all_transactions(csv_base_dir)

    if df.is_empty():
        logger.warning("No transactions found in CSV partitions")
        return {
            "candidate_rows": 0,
            "candidates": 0,
            "pairs": 0,
            "paired": 0,
            "confirmed": 0,
            "unpaired": 0,
            "unconfirmed_candidates": 0,
            "skipped": 0,
            "errors": 0,
        }

    # Filter for transfers (type_raw contains '이체')
    df_transfers = df.filter(pl.col("type_raw").str.contains("이체"))

    logger.info(f"Found {len(df_transfers)} transfer candidates")

    candidates, skipped_count = _build_transfer_candidates(df_transfers)

    if skipped_count > 0:
        logger.info(f"Skipped {skipped_count} transfer candidates with invalid datetime")

    # Detect pairs (reuse existing algorithm - backend-agnostic!)
    transfer_groups = detect_transfer_pairs(candidates)

    # Update DataFrame with paired transfers
    # Create mapping from enumeration index to row_hash for updates
    transfer_hashes = df_transfers["row_hash"].to_list()

    # Build sets of row_hashes for candidate and confirmed transfer states.
    candidate_row_count = len(df_transfers)
    candidate_hashes = {row_hash for row_hash in transfer_hashes if row_hash}
    paired_hashes = set()
    hash_to_group_id = {}

    out_of_bounds_count = 0
    for group_id, txn_ids in transfer_groups.items():
        for txn_id in txn_ids:
            if txn_id < len(transfer_hashes):
                row_hash = transfer_hashes[txn_id]
                paired_hashes.add(row_hash)
                hash_to_group_id[row_hash] = group_id
            else:
                out_of_bounds_count += 1
                logger.error(
                    f"BUG: Transaction ID {txn_id} out of bounds "
                    f"(max: {len(transfer_hashes) - 1}). "
                    f"Group {group_id} may be incomplete."
                )

    if out_of_bounds_count > 0:
        logger.error(f"Found {out_of_bounds_count} out-of-bounds transaction IDs")

    # Ensure transfer_group_id column exists
    if "transfer_group_id" not in df.columns:
        df = df.with_columns(pl.lit(None).alias("transfer_group_id"))
    if "is_transfer_candidate" not in df.columns:
        df = df.with_columns(pl.lit(0).cast(pl.Int64).alias("is_transfer_candidate"))

    # Update full DataFrame
    df = df.with_columns(
        [
            # Mark all transfer-like rows as candidates.
            pl.when(pl.col("row_hash").is_in(list(candidate_hashes)))
            .then(pl.lit(1))
            .otherwise(pl.lit(0))
            .alias("is_transfer_candidate"),
            # Mark only confirmed pairs as transfers.
            pl.when(pl.col("row_hash").is_in(list(paired_hashes)))
            .then(pl.lit(1))
            .otherwise(pl.lit(0))
            .alias("is_transfer"),
            # Set transfer_group_id
            pl.when(pl.col("row_hash").is_in(list(paired_hashes)))
            .then(
                pl.col("row_hash").map_elements(
                    lambda h: hash_to_group_id.get(h), return_dtype=pl.Utf8
                )
            )
            .when(pl.col("row_hash").is_in(list(candidate_hashes)))
            .then(pl.lit(None).cast(pl.Utf8))
            .otherwise(pl.col("transfer_group_id"))
            .alias("transfer_group_id"),
        ]
    )

    # Write updated data back to CSV partitions
    try:
        df = df.with_columns(
            [
                pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").dt.year().alias("_year"),
                pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").dt.month().alias("_month"),
            ]
        )
    except (ValueError, pl.exceptions.PolarsError) as e:
        logger.error(
            f"Failed to parse date column for partitioning: {e}. "
            f"Ensure all dates are in YYYY-MM-DD format."
        )
        raise RuntimeError(f"Date parsing failed during transfer detection: {e}") from e

    for (year, month), group_df in df.group_by(["_year", "_month"]):
        # Remove temporary columns
        partition_df = group_df.drop(["_year", "_month"])
        csv_transactions.write_month(csv_base_dir, partition_df, year, month)

    paired_count = sum(len(ids) for ids in transfer_groups.values())
    unpaired_count = len(candidates) - paired_count
    unconfirmed_candidate_count = max(candidate_row_count - paired_count, 0)

    logger.info(
        f"Transfer detection complete: {len(transfer_groups)} pairs found, "
        f"{paired_count} transactions confirmed, {unpaired_count} valid candidates unpaired"
    )

    return {
        "candidate_rows": candidate_row_count,
        "candidates": len(candidates),
        "pairs": len(transfer_groups),
        "paired": paired_count,
        "confirmed": paired_count,
        "unpaired": unpaired_count,
        "unconfirmed_candidates": unconfirmed_candidate_count,
        "skipped": skipped_count,
        "errors": out_of_bounds_count,
    }
