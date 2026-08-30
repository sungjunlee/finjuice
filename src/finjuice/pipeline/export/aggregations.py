"""
Shared data aggregation functions for multi-format export (Issue #117).

This module provides reusable data calculations for HTML, Markdown, and other
report formats. Functions return Polars DataFrames (for tables/charts) or dicts
(for summary metadata) ready for templating.

Monthly spend, tag breakdown, and top-merchant table aggregations live in
:mod:`finjuice.pipeline.export.aggregations_helpers` and are re-exported
here so existing callers can keep importing from this module.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

from finjuice.pipeline.export.aggregations_helpers import (
    calculate_monthly_spend,  # noqa: F401 — re-exported for existing aggregations imports
    calculate_tag_breakdown,  # noqa: F401 — re-exported for existing aggregations imports
    calculate_top_merchants,  # noqa: F401 — re-exported for existing aggregations imports
)
from finjuice.pipeline.filters import exclude_transfers_for

logger = logging.getLogger(__name__)


def load_transactions(
    csv_base_dir: Path,
    period: Optional[str] = None,
    source_df: "pl.DataFrame | None" = None,
) -> "pl.DataFrame":
    """
    Load transactions from CSV partitions with optional period filter.

    Args:
        csv_base_dir: Base directory for CSV partitions
        period: Optional period filter in YYYY-MM format (e.g., "2024-10")

    Returns:
        Polars DataFrame with transaction data
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    if source_df is None:
        from finjuice.pipeline.storage import csv_transactions

        df = csv_transactions.get_all_transactions(csv_base_dir)
    else:
        df = source_df

    if df.is_empty():
        logger.warning("No transactions found in CSV partitions")
        return df

    # Apply period filter if specified
    if period:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", period):
            raise ValueError(f"Invalid period format: {period}. Expected YYYY-MM (e.g., 2024-10)")
        df = df.filter(pl.col("date").str.starts_with(period))
        if df.is_empty():
            logger.warning(f"No transactions found for period: {period}")

    return df


def calculate_summary_stats(
    df: "pl.DataFrame",
    period: Optional[str] = None,
) -> dict:
    """
    Calculate summary statistics for report header.

    Args:
        df: Polars DataFrame with transactions
        period: Optional period string for display

    Returns:
        Dictionary with summary statistics
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available")

    if df.is_empty():
        return {
            "period": period or "No Data",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_transactions": 0,
            "total_expenses": 0,
            "total_income": 0,
            "date_range_start": None,
            "date_range_end": None,
        }

    # Filter non-transfers for expense/income calculation
    non_transfers = df.filter(exclude_transfers_for(df))

    expenses = non_transfers.filter(pl.col("type_norm") == "expense")
    income = non_transfers.filter(pl.col("type_norm") == "income")

    # Get date range (drop nulls to avoid unexpected start/end values)
    dates = df["date"].drop_nulls().sort()
    date_range_start = dates[0] if len(dates) > 0 else None
    date_range_end = dates[-1] if len(dates) > 0 else None

    # Determine period display
    if period:
        period_display = period
    elif date_range_start and date_range_end:
        period_display = f"{date_range_start} ~ {date_range_end}"
    else:
        period_display = "All Time"

    return {
        "period": period_display,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_transactions": len(df),
        "total_expenses": abs(expenses["amount"].sum()) if len(expenses) > 0 else 0,
        "total_income": income["amount"].sum() if len(income) > 0 else 0,
        "date_range_start": date_range_start,
        "date_range_end": date_range_end,
    }
