"""Write and upsert helpers for transaction CSV partitions.

Owns monthly partition writes, append-with-dedup, and single-row upsert.
Public transaction readers stay in
:mod:`finjuice.pipeline.storage.csv_transactions`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.atomic_files import (
    replace_with_owned_temp as _replace_with_owned_temp,
)
from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.csv_schema import get_partition_path
from finjuice.pipeline.storage.csv_transactions_helpers import _ensure_schema_columns
from finjuice.pipeline.storage.csv_transactions_read_normalize import _empty_transactions_df
from finjuice.pipeline.storage.csv_transactions_serialize import (
    _cast_int_flag_columns,
    _serialize_tag_columns,
)
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors

logger = logging.getLogger(__name__)


def write_month(
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: str = "datetime",
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write transactions to a monthly partition using Polars (atomic operation)."""
    base_dir, authority_data_dir = _authority_transaction_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _write_month_unleased(base_dir, df, year, month, sort_by)


def _write_month_unleased(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: str,
) -> dict[str, Any]:
    """Write one partition while the caller holds the legacy authority lease."""
    partition_path = get_partition_path(base_dir, year, month)
    _assert_no_symlink_ancestors(partition_path, allow_missing=True)
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    if df.height == 0 and df.width == 0:
        df = _empty_transactions_df()
    else:
        df = _ensure_schema_columns(df)

    if sort_by in df.columns:
        df = df.sort(sort_by)

    df = _cast_int_flag_columns(df)
    df = _serialize_tag_columns(df)

    csv_text = df.write_csv(
        None,
        include_header=True,
        separator=",",
        quote_style="necessary",
        line_terminator="\n",
    )
    _replace_with_owned_temp(partition_path, csv_text.encode("utf-8"))

    file_size = partition_path.stat().st_size
    return {
        "row_count": len(df),
        "file_path": str(partition_path),
        "file_size_bytes": file_size,
    }


def append_transactions(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append transactions to appropriate monthly partitions using Polars.

    Distributes rows by (year, month) extracted from 'date' field.
    Optionally deduplicates by row_hash.
    """
    base_dir, authority_data_dir = _authority_transaction_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _append_transactions_unleased(base_dir, df, deduplicate)


def _append_transactions_unleased(
    base_dir: Path,
    df: pl.DataFrame,
    deduplicate: bool,
) -> dict[str, Any]:
    """Append partitions while the caller holds the legacy authority lease."""
    from finjuice.pipeline.storage.csv_transactions import read_month

    if df.height == 0:
        return {
            "total_rows": 0,
            "partitions_updated": 0,
            "rows_inserted": 0,
            "rows_skipped": 0,
        }

    if "date" not in df.columns:
        raise ValueError("DataFrame must have 'date' column for partitioning")

    df = _ensure_schema_columns(df)
    df = df.with_columns(
        [
            pl.col("date").str.slice(0, 4).cast(pl.Int32).alias("_year"),
            pl.col("date").str.slice(5, 2).cast(pl.Int32).alias("_month"),
        ]
    )

    partitions_updated = 0
    rows_inserted = 0
    rows_skipped = 0

    for (year, month), group_df in df.group_by(["_year", "_month"]):
        group_df = group_df.drop(["_year", "_month"])

        if deduplicate:
            original_count = group_df.height
            group_df = group_df.unique(subset=["row_hash"], keep="first")
            within_batch_dupes = original_count - group_df.height
            if within_batch_dupes > 0:
                logger.debug(
                    f"Removed {within_batch_dupes} duplicate(s) within batch for {year}-{month:02d}"
                )
                rows_skipped += within_batch_dupes

        existing_df = read_month(base_dir, int(year), int(month), parse_tags=False)

        if deduplicate and existing_df.height > 0:
            existing_hashes = existing_df.select("row_hash")
            new_rows = group_df.join(
                existing_hashes,
                on="row_hash",
                how="anti",
            )
            rows_skipped += group_df.height - new_rows.height
        else:
            new_rows = group_df

        if new_rows.height > 0:
            if existing_df.height == 0:
                merged_df = new_rows
            else:
                merged_df = pl.concat([existing_df, new_rows])

            _write_month_unleased(base_dir, merged_df, int(year), int(month), "datetime")
            partitions_updated += 1
            rows_inserted += new_rows.height

    return {
        "total_rows": df.height,
        "partitions_updated": partitions_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
    }


def upsert_transaction(
    row: dict[str, Any],
    key_field: str = "row_hash",
    *,
    authority_data_dir: Path,
) -> bool:
    """Update existing transaction or insert new one using Polars.

    Uses 'date' field to determine partition, then row_hash to match.
    Returns True if updated, False if inserted.
    """
    base_dir, authority_data_dir = _authority_transaction_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _upsert_transaction_unleased(base_dir, row, key_field)


def _upsert_transaction_unleased(
    base_dir: Path,
    row: dict[str, Any],
    key_field: str,
) -> bool:
    """Upsert one transaction while the caller holds the legacy authority lease."""
    from finjuice.pipeline.storage.csv_transactions import read_month

    if "date" not in row:
        raise ValueError("Transaction must have 'date' field")

    date_obj = datetime.strptime(row["date"], "%Y-%m-%d")
    year = date_obj.year
    month = date_obj.month

    df = read_month(base_dir, year, month)

    key_value = row.get(key_field)
    if key_value is None:
        raise ValueError(f"Transaction must have '{key_field}' field")

    existing = df.filter(pl.col(key_field) == key_value)

    if existing.height > 0:
        updated_df = df.filter(pl.col(key_field) != key_value)
        updated_df = pl.concat([updated_df, pl.DataFrame([row])])
        updated = True
    else:
        if df.height == 0:
            updated_df = pl.DataFrame([row])
        else:
            updated_df = pl.concat([df, pl.DataFrame([row])])
        updated = False

    _write_month_unleased(base_dir, updated_df, year, month, "datetime")
    return updated


def _authority_transaction_root(authority_data_dir: Path) -> tuple[Path, Path]:
    """Return the only transaction root allowed beneath an explicit data authority."""
    normalized_data_dir = authority_data_dir.expanduser().absolute()
    transaction_root = normalized_data_dir / "transactions"
    _assert_no_symlink_ancestors(transaction_root, allow_missing=True)
    return transaction_root, normalized_data_dir


__all__ = [
    "append_transactions",
    "upsert_transaction",
    "write_month",
]
