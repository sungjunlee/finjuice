"""Report-frame construction and shared export glue for Polars CSV reports.

Owns the Polars availability check, spend/transfer DataFrame aggregations,
transfer source loading, and the mkdir/write/log/return path used by every
public export function. Public export entry points stay in
:mod:`finjuice.pipeline.export.reports_polars`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

from finjuice.pipeline.export.reports_polars_helpers import _write_csv_with_bom
from finjuice.pipeline.filters import exclude_transfers_for, only_transfers

logger = logging.getLogger(__name__)

_TRANSFER_COLUMNS = [
    "datetime",
    "amount",
    "account",
    "counterparty",
    "memo_raw",
    "transfer_group_id",
    "is_transfer_candidate",
    "is_transfer",
]


def _require_polars() -> None:
    """Raise if Polars is not installed."""
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")


def _write_report_output(
    df: pl.DataFrame,
    output_path: Path,
    report_name: str,
) -> int:
    """Write a report DataFrame to CSV with UTF-8 BOM and return the row count."""
    row_count = len(df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv_with_bom(df, output_path)
    logger.info("Exported %s: %s rows", report_name, row_count)
    return row_count


def _aggregate_monthly_spend(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate expense totals by YYYY-MM, excluding internal transfers."""
    assert pl is not None  # guarded by _require_polars
    df = df.with_columns(pl.col("date").str.slice(0, 7).alias("month"))
    df_expense = df.filter((pl.col("type_norm") == "expense") & exclude_transfers_for(df))
    return (
        df_expense.group_by("month")
        .agg(pl.col("amount").sum().round(0).alias("total_spend"))
        .sort("month", descending=True)
    )


def _aggregate_by_tag(df: pl.DataFrame) -> pl.DataFrame | None:
    """Aggregate expense totals by exploded tag, excluding transfers.

    Returns:
        Aggregated tag totals, or ``None`` when no non-empty tags remain
        (the caller should return 0 without writing a report file).
    """
    assert pl is not None  # guarded by _require_polars
    df_filtered = df.filter(exclude_transfers_for(df) & (pl.col("type_norm") == "expense"))
    df_exploded = df_filtered.explode("tags_final")
    df_exploded = df_exploded.filter(
        pl.col("tags_final").is_not_null() & (pl.col("tags_final") != "")
    )
    if df_exploded.is_empty():
        logger.warning("No tags found in transactions")
        return None
    return (
        df_exploded.group_by("tags_final")
        .agg(pl.col("amount").sum().round(0).alias("total"))
        .rename({"tags_final": "tag"})
        .sort(["total", "tag"], descending=False)
    )


def _aggregate_by_category(df: pl.DataFrame) -> pl.DataFrame | None:
    """Aggregate expense totals by ``category_final`` (v3 schema, no double-count).

    Returns:
        Aggregated category totals, or ``None`` when no expense rows remain
        (the caller should return 0 without writing a report file).

    Raises:
        ValueError: If ``category_final`` is missing (likely v2 schema).
    """
    assert pl is not None  # guarded by _require_polars
    if "category_final" not in df.columns:
        logger.error(
            "category_final column not found - data may be v2 schema. "
            "Run migration: python scripts/migrate_schema_v3.py --execute"
        )
        raise ValueError(
            "category_final column not found. Data may be v2 schema. "
            "Run: python scripts/migrate_schema_v3.py --execute"
        )

    df_filtered = df.filter(exclude_transfers_for(df) & (pl.col("type_norm") == "expense"))
    if df_filtered.is_empty():
        logger.warning("No expense transactions found")
        return None
    return (
        df_filtered.group_by("category_final")
        .agg(
            [
                pl.col("amount").sum().round(0).alias("total"),
                pl.col("amount").count().alias("count"),
            ]
        )
        .rename({"category_final": "category"})
        .sort(["total", "category"], descending=False)
    )


def _aggregate_by_account(df: pl.DataFrame) -> pl.DataFrame:
    """Aggregate net totals by account, excluding internal transfers."""
    assert pl is not None  # guarded by _require_polars
    df_non_transfer = df.filter(exclude_transfers_for(df))
    return (
        df_non_transfer.group_by("account")
        .agg(pl.col("amount").sum().round(0).alias("net_total"))
        .sort(["net_total", "account"], descending=False)
    )


def _load_transfer_source_df(
    csv_base_dir: Path,
    source_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Load transfer-audit columns from partitions or a caller-supplied frame."""
    if source_df is None:
        from finjuice.pipeline.storage import csv_transactions

        return csv_transactions.get_all_transactions(csv_base_dir, columns=_TRANSFER_COLUMNS)
    return source_df.select([column for column in _TRANSFER_COLUMNS if column in source_df.columns])


def _aggregate_transfers(df: pl.DataFrame) -> pl.DataFrame | None:
    """Keep confirmed transfer pairs, newest first.

    Returns:
        Sorted transfer rows, or ``None`` when no paired transfers remain
        (the caller should return 0 without writing a report file).
    """
    assert pl is not None  # guarded by _require_polars
    if "is_transfer_candidate" not in df.columns:
        df = df.with_columns(
            pl.col("is_transfer")
            .cast(pl.Int64, strict=False)
            .fill_null(0)
            .alias("is_transfer_candidate")
        )
    df_transfers = df.filter(only_transfers())
    if df_transfers.is_empty():
        logger.info("No paired transfers to export")
        return None
    return df_transfers.sort("datetime", descending=True, maintain_order=True)
