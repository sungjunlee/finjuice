"""Shared transaction-partition readers for checkup collectors."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from finjuice.pipeline.filters import exclude_transfers_for
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA, get_partition_path


def latest_partition_month(csv_base_dir: Path) -> str | None:
    """Return the latest YYYY-MM partition containing transactions.csv."""
    months = [
        f"{path.parent.parent.name}-{path.parent.name}"
        for path in csv_base_dir.glob("*/*/transactions.csv")
        if path.is_file()
    ]
    if not months:
        return None
    return sorted(months)[-1]


def read_month_partition(csv_base_dir: Path, month: str) -> pl.DataFrame | None:
    """Read one month partition using the canonical Polars schema."""
    year, mon = month.split("-", 1)
    partition_path = get_partition_path(csv_base_dir, int(year), int(mon))
    if not partition_path.exists():
        return None

    return pl.read_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )


def read_all_partitions(csv_base_dir: Path) -> pl.DataFrame | None:
    """Read all transaction partitions into one DataFrame."""
    partition_paths = sorted(
        path for path in csv_base_dir.glob("*/*/transactions.csv") if path.is_file()
    )
    if not partition_paths:
        return None

    frames = [
        pl.read_csv(
            path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
        )
        for path in partition_paths
    ]
    return pl.concat(frames, how="diagonal_relaxed") if frames else None


def expense_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Return expense rows with transfers excluded."""
    if df.is_empty() or "amount" not in df.columns:
        return df.head(0)

    expr = pl.col("amount") < 0
    if "type_norm" in df.columns:
        expr = expr & (pl.col("type_norm").cast(pl.Utf8, strict=False) == "expense")
    expr = expr & exclude_transfers_for(df)
    return df.filter(expr)
