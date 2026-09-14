"""
Transfer detection and pairing module (Polars-only).

This module implements deterministic transfer pair detection to identify internal
account transfers (e.g., credit card payments, inter-account transfers) and
prevent double-counting in expense reports.

:func:`detect_transfer_pairs` lives in
:mod:`finjuice.pipeline.transfer.detection_cluster` and is re-exported here so
existing callers can keep importing from this module. Pairing-scoring helpers
live in :mod:`finjuice.pipeline.transfer.detection_helpers`. Candidate
construction lives in :mod:`finjuice.pipeline.transfer.detection_candidates`.
"""

import logging
from pathlib import Path
from typing import Dict

import polars as pl

from finjuice.pipeline.transfer.detection_candidates import (
    TransferCandidate,  # noqa: F401 — re-exported for existing detection imports
    _build_transfer_candidates,
)
from finjuice.pipeline.transfer.detection_cluster import detect_transfer_pairs
from finjuice.pipeline.transfer.detection_helpers import (
    CandidateOrderKey,  # noqa: F401 — re-exported for existing detection imports
    PairOrderKey,  # noqa: F401 — re-exported for existing detection imports
    _build_pair_candidate,  # noqa: F401 — re-exported for existing detection imports
    _candidate_order_key,  # noqa: F401 — re-exported for existing detection imports
    _pair_order_key,  # noqa: F401 — re-exported for existing detection imports
    _sign_rank,  # noqa: F401 — re-exported for existing detection imports
    _TransferPairCandidate,  # noqa: F401 — re-exported for existing detection imports
)

__all__ = [
    "CandidateOrderKey",
    "PairOrderKey",
    "TransferCandidate",
    "_TransferPairCandidate",
    "_build_pair_candidate",
    "_build_transfer_candidates",
    "_candidate_order_key",
    "_pair_order_key",
    "_sign_rank",
    "detect_transfer_pairs",
    "run_transfer_detection",
]

logger = logging.getLogger(__name__)


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
        csv_transactions.write_month(
            partition_df,
            year,
            month,
            authority_data_dir=csv_base_dir.parent,
        )

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
