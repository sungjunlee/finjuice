"""Table-driven CSV partition I/O for Banksalad overview tables.

Owns the generic read/write/append engine keyed by ``_OverviewTableSpec``.
Public overview readers and table contracts stay in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview`.
Write/append wrappers live in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_write`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

_PathBuilder = Callable[[Path, int, int], Path]


@dataclass(frozen=True)
class _OverviewTableSpec:
    """One Banksalad overview CSV table contract."""

    columns: list[str]
    schema: dict[str, Any]
    path_builder: _PathBuilder
    dedup_key: list[str]
    default_sort_by: tuple[str, ...]


def _read_month(
    spec: _OverviewTableSpec,
    base_dir: Path,
    year: int,
    month: int,
    columns: list[str] | None,
) -> pl.DataFrame:
    partition_path = spec.path_builder(base_dir, year, month)

    if not partition_path.exists():
        empty_schema = {col: spec.schema.get(col, pl.Utf8) for col in (columns or spec.columns)}
        return pl.DataFrame(schema=empty_schema)

    df = pl.read_csv(
        partition_path,
        schema_overrides=spec.schema,
        null_values=["", "NA", "NULL"],
    )

    if columns is not None:
        existing_cols = [col for col in columns if col in df.columns]
        if existing_cols:
            df = df.select(existing_cols)

    return df


def _write_partition(
    spec: _OverviewTableSpec,
    partition_path: Path,
    df: pl.DataFrame,
    sort_by: tuple[str, ...],
) -> dict[str, Any]:
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    df = _ensure_columns(df=df, spec=spec)
    df = df.select(spec.columns)

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
    spec: _OverviewTableSpec,
    base_dir: Path,
    df: pl.DataFrame,
    partition_column: str,
    deduplicate: bool,
) -> dict[str, Any]:
    if df.height == 0:
        return _empty_append_result()

    if partition_column not in df.columns:
        raise ValueError(f"DataFrame must have '{partition_column}' column for partitioning")

    df = _ensure_columns(df=df, spec=spec)

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
        group_df = group_df.drop(["_year", "_month"], strict=False).select(spec.columns)

        if deduplicate:
            original_count = group_df.height
            group_df = group_df.unique(subset=spec.dedup_key, keep="first")
            rows_skipped += original_count - group_df.height

        existing_df = _read_month(spec, base_dir, int(year), int(month), None)
        if deduplicate and existing_df.height > 0:
            existing_keys = existing_df.select(spec.dedup_key)
            new_rows = group_df.join(
                existing_keys,
                on=spec.dedup_key,
                how="anti",
                nulls_equal=True,
            )
            rows_skipped += group_df.height - new_rows.height
        else:
            new_rows = group_df

        if new_rows.height > 0:
            merged_df = new_rows if existing_df.height == 0 else pl.concat([existing_df, new_rows])
            _write_partition(
                spec=spec,
                partition_path=spec.path_builder(base_dir, int(year), int(month)),
                df=merged_df,
                sort_by=spec.default_sort_by,
            )
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
    spec: _OverviewTableSpec,
) -> pl.DataFrame:
    for col in spec.columns:
        if col not in df.columns:
            df = df.with_columns(_default_expr(col, spec).alias(col))

    for col, dtype in spec.schema.items():
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(dtype, strict=False).alias(col))

    if "currency" in spec.columns and "currency" in df.columns:
        df = df.with_columns(pl.col("currency").fill_null("KRW").alias("currency"))

    return df


def _default_expr(col: str, spec: _OverviewTableSpec) -> pl.Expr:
    if col == "currency":
        return pl.lit("KRW").cast(pl.Utf8)
    return pl.lit(None).cast(spec.schema.get(col, pl.Utf8))


def _empty_append_result() -> dict[str, Any]:
    return {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }
