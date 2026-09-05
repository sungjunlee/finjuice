"""Transaction CSV partition CRUD (Polars-only, v4 schema).

Extracted from ``csv_partition_polars`` so transaction read/write logic is
separable from asset snapshots and report-filter expression building. Public
helpers remain importable through the original module via re-export.

Schema/column helpers live in
:mod:`finjuice.pipeline.storage.csv_transactions_helpers` and are re-exported
here so existing callers can keep importing from this module.

Write-time integer-flag and tag JSON serialization live in
:mod:`finjuice.pipeline.storage.csv_transactions_serialize` and are
re-exported here so existing callers can keep importing from this module.

Read-time DataFrame normalization (datetime derivation, column projection,
tag JSON decoding, empty-schema fallback) lives in
:mod:`finjuice.pipeline.storage.csv_transactions_read_normalize` and is
re-exported here so existing callers can keep importing from this module.

Write/upsert (``write_month``, ``append_transactions``, ``upsert_transaction``)
lives in :mod:`finjuice.pipeline.storage.csv_transactions_write` and is
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl

from finjuice.pipeline.storage.csv_schema import (
    POLARS_SCHEMA,
    get_partition_path,
)
from finjuice.pipeline.storage.csv_transactions_helpers import (
    _add_read_defaults,
    _ensure_schema_columns,  # noqa: F401 — re-exported for existing csv_transactions imports
    _get_transaction_read_columns,
)
from finjuice.pipeline.storage.csv_transactions_read_normalize import (
    TAG_JSON_COLUMNS,  # noqa: F401 — re-exported for existing csv_transactions imports
    _decode_tag_columns,
    _empty_transactions_df,
    _normalize_datetime_column,
    _project_existing_columns,
)
from finjuice.pipeline.storage.csv_transactions_serialize import (
    _cast_int_flag_columns,  # noqa: F401 — re-exported for existing csv_transactions imports
    _serialize_list,  # noqa: F401 — re-exported for existing csv_transactions imports
    _serialize_tag_columns,  # noqa: F401 — re-exported for existing csv_transactions imports
)
from finjuice.pipeline.storage.csv_transactions_write import (
    append_transactions,
    upsert_transaction,
    write_month,
)


def read_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
    parse_tags: bool = True,
) -> pl.DataFrame:
    """Read transactions for a single month partition (Polars version).

    Builds a Polars CSV scan, then collects the partition into a DataFrame
    because this public helper returns an eager ``pl.DataFrame``. The
    ``columns`` argument selects output columns after datetime normalization;
    it should not be treated as a scan-level projection guarantee.

    Args:
        base_dir: Base directory for partitions
        year: Year
        month: Month (1-12)
        columns: Specific columns to load (None = all)
        parse_tags: If True, parse JSON tag columns to List(Utf8). Set to False
            for internal operations like append_transactions to avoid schema mismatch.

    Returns:
        Polars DataFrame with transactions (empty if partition doesn't exist)
    """
    partition_path = get_partition_path(base_dir, year, month)

    if not partition_path.exists():
        return _empty_transactions_df(columns)

    lf = pl.scan_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )
    df = lf.collect()

    df = _normalize_datetime_column(df)

    df = _add_read_defaults(df, columns)

    df = _project_existing_columns(df, columns)

    if parse_tags:
        df = _decode_tag_columns(df)

    return df


def read_range(
    base_dir: Path,
    start_date: str,
    end_date: str,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read transactions across a date range (multi-month) using Polars.

    This reads each monthly partition eagerly, filters rows after load, then
    concatenates and sorts the resulting DataFrames. The ``columns`` argument
    is applied to the combined DataFrame before JSON tag parsing.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    dfs = []
    current = start.replace(day=1)

    while current <= end:
        partition_path = get_partition_path(base_dir, current.year, current.month)

        if partition_path.exists():
            part_df = pl.read_csv(
                partition_path,
                schema_overrides=POLARS_SCHEMA,
                null_values=["", "NA", "NULL"],
            )

            part_df = _normalize_datetime_column(part_df)

            part_df = _add_read_defaults(part_df, columns)

            part_df = part_df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

            if part_df.height > 0:
                dfs.append(part_df)

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if not dfs:
        return _empty_transactions_df(columns)

    df = pl.concat(dfs)
    if "datetime" in df.columns:
        df = df.sort("datetime")

    df = _project_existing_columns(df, columns)

    return _decode_tag_columns(df)


def find_transaction_by_hash(base_dir: Path, row_hash: str) -> tuple[pl.DataFrame, int, int]:
    """Find the partition containing *row_hash* and return that partition with year/month."""
    normalized_hash = row_hash.strip()
    if not normalized_hash:
        raise ValueError("row_hash cannot be empty.")

    if not base_dir.exists():
        raise FileNotFoundError(f"Transactions directory not found: {base_dir}")

    matches: list[tuple[pl.DataFrame, int, int]] = []

    for year_dir in sorted(base_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue

        year = int(year_dir.name)
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue

            month = int(month_dir.name)
            partition_path = month_dir / "transactions.csv"
            if not partition_path.exists():
                continue

            partition_df = read_month(base_dir, year, month)
            if partition_df.filter(pl.col("row_hash") == normalized_hash).height > 0:
                matches.append((partition_df, year, month))

    if not matches:
        raise FileNotFoundError(f"Transaction not found for row_hash '{normalized_hash}'.")

    if len(matches) > 1:
        raise RuntimeError(f"Multiple transactions found for row_hash '{normalized_hash}'.")

    return matches[0]


def get_all_transactions(base_dir: Path, columns: list[str] | None = None) -> pl.DataFrame:
    """Load all transactions from all partitions as an eager Polars DataFrame.

    Reads each CSV partition eagerly, concatenates the collected DataFrames,
    sorts by datetime, and applies the optional output column projection.
    WARNING: For very large datasets, prefer read_range with date filters.
    """
    if not base_dir.exists():
        return _empty_transactions_df(columns)

    partition_paths = []
    for year_dir in sorted(base_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            partition_path = month_dir / "transactions.csv"
            if partition_path.exists():
                partition_paths.append(partition_path)

    if not partition_paths:
        return _empty_transactions_df(columns)

    dfs = []
    for path in partition_paths:
        read_columns = _get_transaction_read_columns(path, columns)
        part_df = pl.read_csv(
            path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
            columns=read_columns,
        )
        part_df = _normalize_datetime_column(part_df)
        part_df = _add_read_defaults(part_df, columns)
        dfs.append(part_df)

    if not dfs:
        return _empty_transactions_df(columns)

    df = pl.concat(dfs, how="diagonal_relaxed")
    if "datetime" in df.columns:
        df = df.sort("datetime")

    df = _project_existing_columns(df, columns)

    return _decode_tag_columns(df)


__all__ = [
    "append_transactions",
    "find_transaction_by_hash",
    "get_all_transactions",
    "read_month",
    "read_range",
    "upsert_transaction",
    "write_month",
]
