"""
Candidate-construction helpers for transfer detection.

This module owns the :class:`TransferCandidate` model and the Polars row-parsing
helper used by :mod:`finjuice.pipeline.transfer.detection`, which re-exports
them so existing callers can keep importing from the original module.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import polars as pl

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
