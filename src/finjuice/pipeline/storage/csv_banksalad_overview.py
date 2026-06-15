"""Banksalad overview workbook CSV partition CRUD.

ADR-0013 stores source-fidelity overview facts separately from typed balance
and cashflow projections. These helpers intentionally mirror the transaction
and asset snapshot partition API while keeping the overview contracts isolated.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.csv_schema import (
    BANKSALAD_BALANCE_COLUMNS,
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_CASHFLOW_COLUMNS,
    BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
    get_banksalad_balance_partition_path,
    get_banksalad_cashflow_partition_path,
    get_banksalad_overview_facts_partition_path,
)

_PathBuilder = Callable[[Path, int, int], Path]

BANKSALAD_OVERVIEW_FACT_DEDUP_KEY = [
    "snapshot_date",
    "block_id",
    "fact_kind",
    "row_label",
    "column_label",
    "source_row",
    "source_col",
]
BANKSALAD_BALANCE_DEDUP_KEY = ["snapshot_date", "side", "category", "item_name"]
BANKSALAD_CASHFLOW_DEDUP_KEY = ["snapshot_date", "period_month", "category"]


def read_banksalad_overview_facts_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad overview facts for one month partition."""
    return _read_month(
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
        schema=BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
        all_columns=BANKSALAD_OVERVIEW_FACT_COLUMNS,
        path_builder=get_banksalad_overview_facts_partition_path,
    )


def write_banksalad_overview_facts_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "block_id", "source_row", "source_col"),
) -> dict[str, Any]:
    """Write Banksalad overview facts to a monthly partition using atomic replace."""
    return _write_month(
        base_dir=base_dir,
        df=df,
        year=year,
        month=month,
        schema=BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
        all_columns=BANKSALAD_OVERVIEW_FACT_COLUMNS,
        path_builder=get_banksalad_overview_facts_partition_path,
        sort_by=sort_by,
    )


def append_banksalad_overview_facts(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad overview facts partitioned by ``snapshot_date``."""
    return _append_partitioned(
        base_dir=base_dir,
        df=df,
        schema=BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
        all_columns=BANKSALAD_OVERVIEW_FACT_COLUMNS,
        key_columns=BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
        partition_column="snapshot_date",
        read_month=read_banksalad_overview_facts_month,
        write_month=write_banksalad_overview_facts_month,
        deduplicate=deduplicate,
    )


def read_banksalad_balance_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad balance projections for one month partition."""
    return _read_month(
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
        schema=BANKSALAD_BALANCE_POLARS_SCHEMA,
        all_columns=BANKSALAD_BALANCE_COLUMNS,
        path_builder=get_banksalad_balance_partition_path,
    )


def write_banksalad_balance_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("snapshot_date", "side", "category", "item_name"),
) -> dict[str, Any]:
    """Write Banksalad balance projections to a monthly partition using atomic replace."""
    return _write_month(
        base_dir=base_dir,
        df=df,
        year=year,
        month=month,
        schema=BANKSALAD_BALANCE_POLARS_SCHEMA,
        all_columns=BANKSALAD_BALANCE_COLUMNS,
        path_builder=get_banksalad_balance_partition_path,
        sort_by=sort_by,
    )


def append_banksalad_balance(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad balance projections partitioned by ``snapshot_date``."""
    return _append_partitioned(
        base_dir=base_dir,
        df=df,
        schema=BANKSALAD_BALANCE_POLARS_SCHEMA,
        all_columns=BANKSALAD_BALANCE_COLUMNS,
        key_columns=BANKSALAD_BALANCE_DEDUP_KEY,
        partition_column="snapshot_date",
        read_month=read_banksalad_balance_month,
        write_month=write_banksalad_balance_month,
        deduplicate=deduplicate,
    )


def read_banksalad_cashflow_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read Banksalad cashflow projections for one month partition."""
    return _read_month(
        base_dir=base_dir,
        year=year,
        month=month,
        columns=columns,
        schema=BANKSALAD_CASHFLOW_POLARS_SCHEMA,
        all_columns=BANKSALAD_CASHFLOW_COLUMNS,
        path_builder=get_banksalad_cashflow_partition_path,
    )


def write_banksalad_cashflow_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    sort_by: tuple[str, ...] = ("period_month", "category"),
) -> dict[str, Any]:
    """Write Banksalad cashflow projections to a monthly partition using atomic replace."""
    return _write_month(
        base_dir=base_dir,
        df=df,
        year=year,
        month=month,
        schema=BANKSALAD_CASHFLOW_POLARS_SCHEMA,
        all_columns=BANKSALAD_CASHFLOW_COLUMNS,
        path_builder=get_banksalad_cashflow_partition_path,
        sort_by=sort_by,
    )


def append_banksalad_cashflow(
    base_dir: Path, df: pl.DataFrame, deduplicate: bool = True
) -> dict[str, Any]:
    """Append Banksalad cashflow projections.

    Rows are partitioned by ``period_month`` when populated, otherwise by the
    ``snapshot_date`` month. The stored schema always keeps both columns.
    """
    if df.height == 0:
        return _empty_append_result()

    if "period_month" not in df.columns and "snapshot_date" not in df.columns:
        raise ValueError("DataFrame must have 'period_month' or 'snapshot_date' for partitioning")

    df = _ensure_columns(
        df=df,
        schema=BANKSALAD_CASHFLOW_POLARS_SCHEMA,
        all_columns=BANKSALAD_CASHFLOW_COLUMNS,
    )
    df = df.with_columns(_cashflow_partition_source_expr().alias("_partition_source"))

    return _append_partitioned(
        base_dir=base_dir,
        df=df,
        schema=BANKSALAD_CASHFLOW_POLARS_SCHEMA,
        all_columns=BANKSALAD_CASHFLOW_COLUMNS,
        key_columns=BANKSALAD_CASHFLOW_DEDUP_KEY,
        partition_column="_partition_source",
        read_month=read_banksalad_cashflow_month,
        write_month=write_banksalad_cashflow_month,
        deduplicate=deduplicate,
        already_normalized=True,
    )


def _read_month(
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None,
    schema: dict[str, Any],
    all_columns: list[str],
    path_builder: _PathBuilder,
) -> pl.DataFrame:
    partition_path = path_builder(base_dir, year, month)

    if not partition_path.exists():
        empty_schema = {col: schema.get(col, pl.Utf8) for col in (columns or all_columns)}
        return pl.DataFrame(schema=empty_schema)

    df = pl.read_csv(
        partition_path,
        schema_overrides=schema,
        null_values=["", "NA", "NULL"],
    )

    if columns is not None:
        existing_cols = [col for col in columns if col in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    return df


def _write_month(
    base_dir: Path,
    df: pl.DataFrame,
    year: int,
    month: int,
    schema: dict[str, Any],
    all_columns: list[str],
    path_builder: _PathBuilder,
    sort_by: tuple[str, ...],
) -> dict[str, Any]:
    partition_path = path_builder(base_dir, year, month)
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    df = _ensure_columns(df=df, schema=schema, all_columns=all_columns)
    df = df.select(all_columns)

    sort_columns = [col for col in sort_by if col in df.columns]
    if sort_columns:
        df = df.sort(sort_columns, nulls_last=True)

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


def _append_partitioned(
    base_dir: Path,
    df: pl.DataFrame,
    schema: dict[str, Any],
    all_columns: list[str],
    key_columns: list[str],
    partition_column: str,
    read_month: Callable[[Path, int, int, list[str] | None], pl.DataFrame],
    write_month: Callable[[Path, pl.DataFrame, int, int], dict[str, Any]],
    deduplicate: bool,
    already_normalized: bool = False,
) -> dict[str, Any]:
    if df.height == 0:
        return _empty_append_result()

    if partition_column not in df.columns:
        raise ValueError(f"DataFrame must have '{partition_column}' column for partitioning")

    if not already_normalized:
        df = _ensure_columns(df=df, schema=schema, all_columns=all_columns)

    df = df.with_columns(
        [
            pl.col(partition_column).str.slice(0, 4).cast(pl.Int32).alias("_year"),
            pl.col(partition_column).str.slice(5, 2).cast(pl.Int32).alias("_month"),
        ]
    )

    partitions_updated = 0
    rows_inserted = 0
    rows_skipped = 0

    for (year, month), group_df in df.group_by(["_year", "_month"]):
        group_df = group_df.drop(["_year", "_month"], strict=False).select(all_columns)

        if deduplicate:
            original_count = group_df.height
            group_df = group_df.unique(subset=key_columns, keep="first")
            rows_skipped += original_count - group_df.height

        existing_df = read_month(base_dir, int(year), int(month), None)
        if deduplicate and existing_df.height > 0:
            existing_keys = existing_df.select(key_columns)
            new_rows = group_df.join(
                existing_keys,
                on=key_columns,
                how="anti",
                nulls_equal=True,
            )
            rows_skipped += group_df.height - new_rows.height
        else:
            new_rows = group_df

        if new_rows.height > 0:
            merged_df = new_rows if existing_df.height == 0 else pl.concat([existing_df, new_rows])
            write_month(base_dir, merged_df, int(year), int(month))
            partitions_updated += 1
            rows_inserted += new_rows.height

    return {
        "total_rows": df.height,
        "partitions_updated": partitions_updated,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
    }


def _ensure_columns(
    df: pl.DataFrame,
    schema: dict[str, Any],
    all_columns: list[str],
) -> pl.DataFrame:
    for col in all_columns:
        if col not in df.columns:
            df = df.with_columns(_default_expr(col, schema).alias(col))

    for col, dtype in schema.items():
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(dtype, strict=False).alias(col))

    if "currency" in all_columns and "currency" in df.columns:
        df = df.with_columns(pl.col("currency").fill_null("KRW").alias("currency"))

    return df


def _default_expr(col: str, schema: dict[str, Any]) -> pl.Expr:
    if col == "currency":
        return pl.lit("KRW").cast(pl.Utf8)
    return pl.lit(None).cast(schema.get(col, pl.Utf8))


def _cashflow_partition_source_expr() -> pl.Expr:
    period_month = pl.col("period_month").cast(pl.Utf8, strict=False).str.strip_chars()
    snapshot_month = pl.col("snapshot_date").cast(pl.Utf8, strict=False).str.slice(0, 7)
    return (
        pl.when(period_month.is_not_null() & (period_month != ""))
        .then(period_month)
        .otherwise(snapshot_month)
    )


def _empty_append_result() -> dict[str, Any]:
    return {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }


__all__ = [
    "BANKSALAD_BALANCE_DEDUP_KEY",
    "BANKSALAD_CASHFLOW_DEDUP_KEY",
    "BANKSALAD_OVERVIEW_FACT_DEDUP_KEY",
    "append_banksalad_balance",
    "append_banksalad_cashflow",
    "append_banksalad_overview_facts",
    "read_banksalad_balance_month",
    "read_banksalad_cashflow_month",
    "read_banksalad_overview_facts_month",
    "write_banksalad_balance_month",
    "write_banksalad_cashflow_month",
    "write_banksalad_overview_facts_month",
]
