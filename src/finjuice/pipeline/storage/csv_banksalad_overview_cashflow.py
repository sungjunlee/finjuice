"""Cashflow partition-source helpers for Banksalad overview CSV tables.

Owns period_month vs snapshot_date partition-key derivation and YYYY-MM
validation. Public cashflow readers stay in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview`, which re-exports
these helpers so existing callers can keep importing from that module.
Write/append wrappers live in
:mod:`finjuice.pipeline.storage.csv_banksalad_overview_write`.
"""

from __future__ import annotations

import polars as pl


def _cashflow_partition_source_expr() -> pl.Expr:
    period_month = pl.col("period_month").cast(pl.Utf8, strict=False).str.strip_chars()
    snapshot_month = pl.col("snapshot_date").cast(pl.Utf8, strict=False).str.slice(0, 7)
    return (
        pl.when(period_month.is_not_null() & (period_month != ""))
        .then(period_month)
        .otherwise(snapshot_month)
    )


def _validate_cashflow_partition_source(df: pl.DataFrame) -> None:
    valid_source = (
        pl.col("_partition_source")
        .cast(pl.Utf8, strict=False)
        .str.contains(r"^\d{4}-\d{2}$")
        .fill_null(False)
    )
    invalid_count = df.select((~valid_source).sum().alias("invalid_count")).item()
    if invalid_count:
        raise ValueError("Cashflow partition source must be populated as YYYY-MM")
