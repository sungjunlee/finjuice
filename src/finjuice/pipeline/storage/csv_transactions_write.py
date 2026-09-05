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

from finjuice.pipeline.storage.csv_schema import get_partition_path
from finjuice.pipeline.storage.csv_transactions_helpers import _ensure_schema_columns
from finjuice.pipeline.storage.csv_transactions_read_normalize import _empty_transactions_df
from finjuice.pipeline.storage.csv_transactions_serialize import (
    _cast_int_flag_columns,
    _serialize_tag_columns,
)

logger = logging.getLogger(__name__)


def write_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: str = "datetime",
) -> dict[str, Any]:
    """Write transactions to a monthly partition using Polars (atomic operation)."""
    partition_path = get_partition_path(base_dir, year, month)
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    if df.height == 0 and df.width == 0:
        df = _empty_transactions_df()
    else:
        df = _ensure_schema_columns(df)

    if sort_by in df.columns:
        df = df.sort(sort_by)

    df = _cast_int_flag_columns(df)
    df = _serialize_tag_columns(df)

    tmp_path = partition_path.with_suffix(".tmp")
    df.write_csv(
        tmp_path,
        include_header=True,
        separator=",",
        quote_style="necessary",
        line_terminator="\n",
    )
    tmp_path.replace(partition_path)

    file_size = partition_path.stat().st_size
    return {
        "row_count": len(df),
        "file_path": str(partition_path),
        "file_size_bytes": file_size,
    }


def append_transactions(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append transactions to appropriate monthly partitions using Polars.

    Distributes rows by (year, month) extracted from 'date' field.
    Optionally deduplicates by row_hash.
    """
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

            write_month(base_dir, merged_df, int(year), int(month))
            partitions_updated += 1
            rows_inserted += new_rows.height

    return {
        "total_rows": df.height,
        "partitions_updated": partitions_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
    }


def upsert_transaction(base_dir: Path, row: dict[str, Any], key_field: str = "row_hash") -> bool:
    """Update existing transaction or insert new one using Polars.

    Uses 'date' field to determine partition, then row_hash to match.
    Returns True if updated, False if inserted.
    """
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

    write_month(base_dir, updated_df, year, month)
    return updated


__all__ = [
    "append_transactions",
    "upsert_transaction",
    "write_month",
]
