"""Transaction CSV partition CRUD (Polars-only, v4 schema).

Extracted from ``csv_partition_polars`` so transaction read/write logic is
separable from asset snapshots and report-filter expression building. Public
helpers remain importable through the original module via re-export.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.csv_schema import (
    CSV_COLUMNS,
    POLARS_SCHEMA,
    get_partition_path,
)

logger = logging.getLogger(__name__)


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
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
        return pl.DataFrame(schema=schema)

    lf = pl.scan_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )
    df = lf.collect()

    if "datetime" not in df.columns and "date" in df.columns:
        if "time" in df.columns:
            df = df.with_columns((pl.col("date") + "T" + pl.col("time")).alias("datetime"))
        else:
            df = df.with_columns((pl.col("date") + "T00:00:00").alias("datetime"))

    df = _add_read_defaults(df, columns)

    if columns is not None:
        existing_cols = [c for c in columns if c in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    if parse_tags:
        tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
        for col in tag_columns:
            if col in df.columns:
                df = df.with_columns(pl.col(col).str.json_decode(dtype=pl.List(pl.Utf8)).alias(col))

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

            if "datetime" not in part_df.columns and "date" in part_df.columns:
                if "time" in part_df.columns:
                    part_df = part_df.with_columns(
                        (pl.col("date") + "T" + pl.col("time")).alias("datetime")
                    )
                else:
                    part_df = part_df.with_columns((pl.col("date") + "T00:00:00").alias("datetime"))

            part_df = _add_read_defaults(part_df, columns)

            part_df = part_df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

            if part_df.height > 0:
                dfs.append(part_df)

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if not dfs:
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
        return pl.DataFrame(schema=schema)

    df = pl.concat(dfs)
    if "datetime" in df.columns:
        df = df.sort("datetime")

    if columns is not None:
        existing_cols = [c for c in columns if c in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            df = df.with_columns(pl.col(col).str.json_decode(dtype=pl.List(pl.Utf8)).alias(col))

    return df


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
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in CSV_COLUMNS}
        df = pl.DataFrame(schema=schema)
    else:
        df = _ensure_schema_columns(df)

    if sort_by in df.columns:
        df = df.sort(sort_by)

    int_columns = ["needs_review", "is_transfer_candidate", "is_transfer", "source_row"]
    for col in int_columns:
        if col in df.columns:
            column_expr = pl.col(col).cast(pl.Int64, strict=False)
            if col in {"is_transfer_candidate", "is_transfer"}:
                column_expr = column_expr.fill_null(0)
            df = df.with_columns(column_expr.alias(col))

    def serialize_list(x: Any) -> str:
        """Serialize tag collections to JSON string without double-encoding."""
        if x is None:
            return "[]"
        if isinstance(x, str):
            stripped = x.strip()
            return "[]" if stripped == "" else stripped
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            return json.dumps(list(x), ensure_ascii=False)
        return json.dumps([x], ensure_ascii=False)

    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).map_elements(serialize_list, return_dtype=pl.Utf8).alias(col)
            )

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
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
        return pl.DataFrame(schema=schema)

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
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
        return pl.DataFrame(schema=schema)

    dfs = []
    for path in partition_paths:
        read_columns = _get_transaction_read_columns(path, columns)
        part_df = pl.read_csv(
            path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
            columns=read_columns,
        )
        if "datetime" not in part_df.columns and "date" in part_df.columns:
            if "time" in part_df.columns:
                part_df = part_df.with_columns(
                    (pl.col("date") + "T" + pl.col("time")).alias("datetime")
                )
            else:
                part_df = part_df.with_columns((pl.col("date") + "T00:00:00").alias("datetime"))
        part_df = _add_read_defaults(part_df, columns)
        dfs.append(part_df)

    if not dfs:
        schema = {col: POLARS_SCHEMA.get(col, pl.Utf8) for col in (columns or CSV_COLUMNS)}
        return pl.DataFrame(schema=schema)

    df = pl.concat(dfs, how="diagonal_relaxed")
    if "datetime" in df.columns:
        df = df.sort("datetime")

    if columns is not None:
        existing_cols = [c for c in columns if c in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            df = df.with_columns(pl.col(col).str.json_decode(dtype=pl.List(pl.Utf8)).alias(col))

    return df


def _get_transaction_read_columns(path: Path, columns: list[str] | None) -> list[str] | None:
    """Return CSV columns needed for output projection plus datetime sorting."""
    if columns is None:
        return None

    with path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle), [])

    available = set(header)
    read_columns = [column for column in columns if column in available]
    if "is_transfer_candidate" in columns and "is_transfer_candidate" not in available:
        if "is_transfer" in available:
            read_columns.append("is_transfer")

    if "datetime" in available:
        read_columns.append("datetime")
    elif "date" in available:
        read_columns.append("date")
        if "time" in available:
            read_columns.append("time")

    return list(dict.fromkeys(read_columns)) or None


def _add_read_defaults(df: pl.DataFrame, columns: list[str] | None = None) -> pl.DataFrame:
    """Backfill additive read-time defaults for older compatible partitions."""
    defaults: list[pl.Expr] = []
    needs_notes = columns is None or "notes_manual" in columns
    needs_candidate = columns is None or "is_transfer_candidate" in columns
    needs_group_id = columns is None or "transfer_group_id" in columns

    if needs_notes and "notes_manual" not in df.columns:
        defaults.append(pl.lit("").cast(pl.Utf8).alias("notes_manual"))
    elif needs_notes:
        defaults.append(pl.col("notes_manual").cast(pl.Utf8, strict=False).fill_null(""))

    if needs_candidate and "is_transfer_candidate" not in df.columns:
        if "is_transfer" in df.columns:
            defaults.append(
                pl.col("is_transfer")
                .cast(pl.Int64, strict=False)
                .fill_null(0)
                .alias("is_transfer_candidate")
            )
        else:
            defaults.append(pl.lit(0).cast(pl.Int64).alias("is_transfer_candidate"))

    if needs_group_id and "transfer_group_id" not in df.columns:
        defaults.append(pl.lit(None).cast(pl.Utf8).alias("transfer_group_id"))

    if not defaults:
        return df
    return df.with_columns(defaults)


def _ensure_schema_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Ensure all CSV schema columns exist with appropriate defaults.

    Handles test data or incomplete DataFrames by adding missing columns with
    sensible defaults (empty lists for tags, None for optional fields, etc.).
    """
    defaults = {
        "row_hash": pl.lit(None).cast(pl.Utf8),
        "date": pl.lit(None).cast(pl.Utf8),
        "time": pl.lit(None).cast(pl.Utf8),
        "type_raw": pl.lit(None).cast(pl.Utf8),
        "type_norm": pl.lit(None).cast(pl.Utf8),
        "major_raw": pl.lit(None).cast(pl.Utf8),
        "minor_raw": pl.lit(None).cast(pl.Utf8),
        "merchant_raw": pl.lit(None).cast(pl.Utf8),
        "memo_raw": pl.lit(None).cast(pl.Utf8),
        "notes_manual": pl.lit("").cast(pl.Utf8),
        "account": pl.lit(None).cast(pl.Utf8),
        "currency": pl.lit("KRW").cast(pl.Utf8),
        "counterparty": pl.lit(None).cast(pl.Utf8),
        "datetime": pl.lit(None).cast(pl.Utf8),
        "category_rule": pl.lit(None).cast(pl.Utf8),
        "category_final": pl.lit("미분류").cast(pl.Utf8),
        "transfer_group_id": pl.lit(None).cast(pl.Utf8),
        "file_id": pl.lit(None).cast(pl.Utf8),
        "amount": pl.lit(None).cast(pl.Float64),
        "confidence": pl.lit(None).cast(pl.Float64),
        "needs_review": pl.lit(0).cast(pl.Int64),
        "is_transfer_candidate": pl.lit(0).cast(pl.Int64),
        "is_transfer": pl.lit(0).cast(pl.Int64),
        "source_row": pl.lit(None).cast(pl.Int64),
        "tags_rule": pl.lit("[]").cast(pl.Utf8),
        "tags_ai": pl.lit("[]").cast(pl.Utf8),
        "tags_manual": pl.lit("[]").cast(pl.Utf8),
        "tags_final": pl.lit("[]").cast(pl.Utf8),
    }

    tag_columns = ["tags_rule", "tags_ai", "tags_manual", "tags_final"]
    for col in tag_columns:
        if col in df.columns:
            col_dtype = df.schema[col]
            if isinstance(col_dtype, pl.List):
                df = df.with_columns(
                    pl.col(col)
                    .map_elements(
                        lambda x: json.dumps(list(x) if x is not None else []), return_dtype=pl.Utf8
                    )
                    .alias(col)
                )

    def _null_if_blank(column_name: str) -> pl.Expr:
        """Convert blank strings to null for category fallback chain."""
        return pl.col(column_name).cast(pl.Utf8, strict=False).str.strip_chars().replace("", None)

    if "category_rule" not in df.columns:
        df = df.with_columns(defaults["category_rule"].alias("category_rule"))
    else:
        df = df.with_columns(_null_if_blank("category_rule").alias("category_rule"))

    fallback_candidates: list[pl.Expr] = [_null_if_blank("category_rule")]
    fallback_candidates.append(
        _null_if_blank("minor_raw") if "minor_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(
        _null_if_blank("major_raw") if "major_raw" in df.columns else pl.lit(None).cast(pl.Utf8)
    )
    fallback_candidates.append(pl.lit("미분류").cast(pl.Utf8))
    fallback_expr = pl.coalesce(fallback_candidates)

    if "category_final" not in df.columns:
        df = df.with_columns(fallback_expr.alias("category_final"))
    else:
        df = df.with_columns(
            pl.when(_null_if_blank("category_final").is_not_null())
            .then(pl.col("category_final").cast(pl.Utf8, strict=False))
            .otherwise(fallback_expr)
            .alias("category_final")
        )

    for col in CSV_COLUMNS:
        if col not in df.columns:
            if col in defaults:
                df = df.with_columns(defaults[col].alias(col))
            else:
                df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))

    schema_columns = [col for col in CSV_COLUMNS if col in df.columns]
    extra_columns = [col for col in df.columns if col not in CSV_COLUMNS]
    return df.select(schema_columns + extra_columns)


__all__ = [
    "append_transactions",
    "find_transaction_by_hash",
    "get_all_transactions",
    "read_month",
    "read_range",
    "upsert_transaction",
    "write_month",
]
