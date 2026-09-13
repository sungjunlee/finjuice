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

from finjuice.pipeline.storage.atomic_files import (
    replace_with_owned_temp as _replace_with_owned_temp,
)
from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_COLUMNS,
    ASSET_SNAPSHOT_POLARS_SCHEMA,
    get_asset_snapshot_partition_path,
)
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors

logger = logging.getLogger(__name__)

_ASSET_SNAPSHOT_ROOT = ("assets", "snapshots")
_ASSET_DEDUP_KEY = ["snapshot_date", "account_id", "instrument_id"]
_EMPTY_APPEND_RESULT = {
    "total_rows": 0,
    "partitions_updated": 0,
    "rows_inserted": 0,
    "rows_skipped": 0,
}


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
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "account_id", "instrument_id"),
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Write asset snapshots to a monthly partition using atomic replace."""
    base_dir, authority_data_dir = _authority_asset_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _write_asset_snapshot_month_unleased(base_dir, df, year, month, sort_by)


def _write_asset_snapshot_month_unleased(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...],
) -> dict[str, Any]:
    """Write one snapshot partition while the caller holds the legacy lease."""
    partition_path = get_asset_snapshot_partition_path(base_dir, year, month)
    _assert_no_symlink_ancestors(partition_path, allow_missing=True)
    partition_path.parent.mkdir(parents=True, exist_ok=True)
    df = _prepared_asset_snapshot_frame(df, sort_by)
    _replace_with_owned_temp(partition_path, _asset_csv_bytes(df))
    return {
        "row_count": df.height,
        "file_path": str(partition_path),
        "file_size_bytes": partition_path.stat().st_size,
    }


def append_asset_snapshots(
    df: pl.DataFrame,
    deduplicate: bool = True,
    *,
    authority_data_dir: Path,
) -> dict[str, Any]:
    """Append asset snapshots to monthly partitions.

    Dedup key (daily grain): snapshot_date, account_id, instrument_id.
    """
    base_dir, authority_data_dir = _authority_asset_root(authority_data_dir)
    with legacy_write_lease(authority_data_dir):
        return _append_asset_snapshots_unleased(base_dir, df, deduplicate)


def _append_asset_snapshots_unleased(
    base_dir: Path,
    df: pl.DataFrame,
    deduplicate: bool,
) -> dict[str, Any]:
    """Append snapshot partitions while the caller holds the legacy lease."""
    if df.height == 0:
        return dict(_EMPTY_APPEND_RESULT)
    if "snapshot_date" not in df.columns:
        raise ValueError("DataFrame must have 'snapshot_date' column for partitioning")

    df = _ensure_asset_snapshot_columns(df)
    df = df.with_columns(
        [
            pl.col("snapshot_date").str.slice(0, 4).cast(pl.Int32).alias("_year"),
            pl.col("snapshot_date").str.slice(5, 2).cast(pl.Int32).alias("_month"),
        ]
    )
    return _append_asset_groups(base_dir, df, deduplicate)


def _append_asset_groups(
    base_dir: Path,
    df: pl.DataFrame,
    deduplicate: bool,
) -> dict[str, Any]:
    """Merge each month group into its partition under a held lease."""
    partitions_updated = 0
    rows_inserted = 0
    rows_skipped = 0
    for (year, month), group_df in df.group_by(["_year", "_month"]):
        inserted, skipped, updated = _append_asset_group(
            base_dir, (int(year), int(month)), group_df, deduplicate
        )
        rows_inserted += inserted
        rows_skipped += skipped
        partitions_updated += updated
    return {
        "total_rows": df.height,
        "partitions_updated": partitions_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
    }


def _append_asset_group(
    base_dir: Path,
    year_month: tuple[int, int],
    group_df: pl.DataFrame,
    deduplicate: bool,
) -> tuple[int, int, int]:
    """Insert one month group and return inserted, skipped, and updated-partition flags."""
    year, month = year_month
    group_df = group_df.drop(["_year", "_month"]).select(ASSET_SNAPSHOT_COLUMNS)
    skipped = 0
    if deduplicate:
        original_count = group_df.height
        group_df = group_df.unique(subset=_ASSET_DEDUP_KEY, keep="first")
        skipped += original_count - group_df.height
    existing_df = read_asset_snapshot_month(base_dir, year, month)
    new_rows, extra_skipped = _new_asset_rows(group_df, existing_df, deduplicate)
    skipped += extra_skipped
    if new_rows.height == 0:
        return 0, skipped, 0
    _write_merged_asset_partition(base_dir, existing_df, new_rows, year, month)
    return new_rows.height, skipped, 1


def _write_merged_asset_partition(
    base_dir: Path,
    existing_df: pl.DataFrame,
    new_rows: pl.DataFrame,
    year: int,
    month: int,
) -> None:
    merged_df = new_rows if existing_df.height == 0 else pl.concat([existing_df, new_rows])
    sort_by = ("snapshot_date", "account_id", "instrument_id")
    _write_asset_snapshot_month_unleased(base_dir, merged_df, year, month, sort_by)


def _new_asset_rows(
    group_df: pl.DataFrame,
    existing_df: pl.DataFrame,
    deduplicate: bool,
) -> tuple[pl.DataFrame, int]:
    """Return rows that should be inserted against an existing partition."""
    if not (deduplicate and existing_df.height > 0):
        return group_df, 0
    new_rows = group_df.join(existing_df.select(_ASSET_DEDUP_KEY), on=_ASSET_DEDUP_KEY, how="anti")
    return new_rows, group_df.height - new_rows.height


def _asset_csv_bytes(df: pl.DataFrame) -> bytes:
    """Serialize one partition in memory before the atomic replace."""
    return df.write_csv(
        None,
        include_header=True,
        separator=",",
        quote_style="necessary",
        line_terminator="\n",
    ).encode("utf-8")


def _prepared_asset_snapshot_frame(df: pl.DataFrame, sort_by: tuple[str, ...]) -> pl.DataFrame:
    """Apply schema defaults and the requested sort before serialization."""
    df = _ensure_asset_snapshot_columns(df).select(ASSET_SNAPSHOT_COLUMNS)
    sort_columns = [col for col in sort_by if col in df.columns]
    if sort_columns:
        df = df.sort(sort_columns)
    return df


def _authority_asset_root(authority_data_dir: Path) -> tuple[Path, Path]:
    """Return the only asset snapshot root allowed beneath an explicit data authority."""
    normalized_data_dir = authority_data_dir.expanduser().absolute()
    snapshot_root = normalized_data_dir.joinpath(*_ASSET_SNAPSHOT_ROOT)
    _assert_no_symlink_ancestors(snapshot_root, allow_missing=True)
    return snapshot_root, normalized_data_dir


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
