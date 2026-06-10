"""Asset snapshot CSV partition CRUD (Polars-only).

Extracted from ``csv_partition_polars`` so asset snapshot read/write is
separable from transaction CRUD. Public helpers remain importable through the
original module via re-export.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_COLUMNS,
    ASSET_SNAPSHOT_POLARS_SCHEMA,
    get_asset_snapshot_partition_path,
)

logger = logging.getLogger(__name__)


def read_asset_snapshot_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read asset snapshots for a single month partition."""
    partition_path = get_asset_snapshot_partition_path(base_dir, year, month)

    if not partition_path.exists():
        schema = {
            col: ASSET_SNAPSHOT_POLARS_SCHEMA.get(col, pl.Utf8)
            for col in (columns or ASSET_SNAPSHOT_COLUMNS)
        }
        return pl.DataFrame(schema=schema)

    df = pl.read_csv(
        partition_path,
        schema_overrides=ASSET_SNAPSHOT_POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )

    if columns is not None:
        existing_cols = [col for col in columns if col in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    return df


def write_asset_snapshot_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "account_id", "instrument_id"),
) -> dict[str, Any]:
    """Write asset snapshots to a monthly partition using atomic replace."""
    partition_path = get_asset_snapshot_partition_path(base_dir, year, month)
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    df = _ensure_asset_snapshot_columns(df)
    df = df.select(ASSET_SNAPSHOT_COLUMNS)

    sort_columns = [col for col in sort_by if col in df.columns]
    if sort_columns:
        df = df.sort(sort_columns)

    tmp_path = partition_path.with_suffix(".tmp")
    df.write_csv(
        tmp_path,
        include_header=True,
        separator=",",
        quote_style="necessary",
        line_terminator="\n",
    )
    tmp_path.replace(partition_path)

    return {
        "row_count": df.height,
        "file_path": str(partition_path),
        "file_size_bytes": partition_path.stat().st_size,
    }


def append_asset_snapshots(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append asset snapshots to monthly partitions.

    Dedup key (daily grain): snapshot_date, account_id, instrument_id.
    """
    if df.height == 0:
        return {
            "total_rows": 0,
            "partitions_updated": 0,
            "rows_inserted": 0,
            "rows_skipped": 0,
        }

    if "snapshot_date" not in df.columns:
        raise ValueError("DataFrame must have 'snapshot_date' column for partitioning")

    key_columns = ["snapshot_date", "account_id", "instrument_id"]
    df = _ensure_asset_snapshot_columns(df)
    df = df.with_columns(
        [
            pl.col("snapshot_date").str.slice(0, 4).cast(pl.Int32).alias("_year"),
            pl.col("snapshot_date").str.slice(5, 2).cast(pl.Int32).alias("_month"),
        ]
    )

    partitions_updated = 0
    rows_inserted = 0
    rows_skipped = 0

    for (year, month), group_df in df.group_by(["_year", "_month"]):
        group_df = group_df.drop(["_year", "_month"]).select(ASSET_SNAPSHOT_COLUMNS)

        if deduplicate:
            original_count = group_df.height
            group_df = group_df.unique(subset=key_columns, keep="first")
            rows_skipped += original_count - group_df.height

        existing_df = read_asset_snapshot_month(base_dir, int(year), int(month))
        if deduplicate and existing_df.height > 0:
            existing_keys = existing_df.select(key_columns)
            new_rows = group_df.join(existing_keys, on=key_columns, how="anti")
            rows_skipped += group_df.height - new_rows.height
        else:
            new_rows = group_df

        if new_rows.height > 0:
            merged_df = new_rows if existing_df.height == 0 else pl.concat([existing_df, new_rows])
            write_asset_snapshot_month(base_dir, merged_df, int(year), int(month))
            partitions_updated += 1
            rows_inserted += new_rows.height

    return {
        "total_rows": df.height,
        "partitions_updated": partitions_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
    }


def _ensure_asset_snapshot_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Ensure all asset snapshot schema columns exist with defaults."""
    defaults = {
        "snapshot_date": pl.lit(None).cast(pl.Utf8),
        "account_id": pl.lit(None).cast(pl.Utf8),
        "instrument_id": pl.lit(None).cast(pl.Utf8),
        "quantity": pl.lit(None).cast(pl.Float64),
        "market_value": pl.lit(None).cast(pl.Float64),
        "currency": pl.lit("KRW").cast(pl.Utf8),
        "file_id": pl.lit(None).cast(pl.Utf8),
        "source_row": pl.lit(None).cast(pl.Int64),
    }

    for col in ASSET_SNAPSHOT_COLUMNS:
        if col not in df.columns:
            df = df.with_columns(defaults[col].alias(col))

    for col, dtype in ASSET_SNAPSHOT_POLARS_SCHEMA.items():
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(dtype, strict=False).alias(col))

    return df


__all__ = [
    "append_asset_snapshots",
    "read_asset_snapshot_month",
    "write_asset_snapshot_month",
]
