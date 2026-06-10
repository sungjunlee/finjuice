"""
Shared data aggregation functions for multi-format export (Issue #117).

This module provides reusable data calculations for HTML, Markdown, and other
report formats. Functions return Polars DataFrames (for tables/charts) or dicts
(for summary metadata) ready for templating.
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


def calculate_monthly_spend(
    df: "pl.DataFrame",
    exclude_transfers: bool = True,
    exclude_income: bool = True,
) -> "pl.DataFrame":
    """
    Calculate monthly spending totals.

    Args:
        df: Polars DataFrame with transactions
        exclude_transfers: Exclude internal transfers (default: True)
        exclude_income: Exclude income transactions (default: True)

    Returns:
        DataFrame with columns: [month, transaction_count, total_amount]
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available")

    if df.is_empty():
        return pl.DataFrame(
            {"month": [], "transaction_count": [], "total_amount": []},
            schema={"month": pl.Utf8, "transaction_count": pl.UInt32, "total_amount": pl.Float64},
        )

    # Add month column
    df = df.with_columns(pl.col("date").str.slice(0, 7).alias("month"))

    # Apply filters
    filtered = df
    if exclude_transfers:
        filtered = filtered.filter(exclude_transfers_for(filtered))
    if exclude_income:
        filtered = filtered.filter(pl.col("type_norm") == "expense")

    # Aggregate by month
    result = (
        filtered.group_by("month")
        .agg(
            pl.len().alias("transaction_count"),
            pl.col("amount").sum().round(0).alias("total_amount"),
        )
        .sort("month", descending=True)
    )

    return result


def calculate_tag_breakdown(
    df: "pl.DataFrame",
    top_n: int = 10,
    exclude_transfers: bool = True,
    exclude_income: bool = True,
) -> "pl.DataFrame":
    """
    Calculate spending breakdown by tag.

    Args:
        df: Polars DataFrame with transactions
        top_n: Number of top tags to return (default: 10)
        exclude_transfers: Exclude transfers (default: True)
        exclude_income: Exclude income transactions (default: True)

    Returns:
        DataFrame with columns: [tag, transaction_count, total_amount, percentage]
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available")

    if df.is_empty():
        return pl.DataFrame(
            {"tag": [], "transaction_count": [], "total_amount": [], "percentage": []},
            schema={
                "tag": pl.Utf8,
                "transaction_count": pl.UInt32,
                "total_amount": pl.Float64,
                "percentage": pl.Float64,
            },
        )

    # Apply filters
    filtered = df
    if exclude_transfers:
        filtered = filtered.filter(exclude_transfers_for(filtered))
    if exclude_income:
        filtered = filtered.filter(pl.col("type_norm") == "expense")

    # Explode tags_final array
    exploded = filtered.explode("tags_final")

    # Filter out empty tags
    exploded = exploded.filter(pl.col("tags_final").is_not_null() & (pl.col("tags_final") != ""))

    if exploded.is_empty():
        return pl.DataFrame(
            {"tag": [], "transaction_count": [], "total_amount": [], "percentage": []},
            schema={
                "tag": pl.Utf8,
                "transaction_count": pl.UInt32,
                "total_amount": pl.Float64,
                "percentage": pl.Float64,
            },
        )

    # Aggregate by tag
    result = (
        exploded.group_by("tags_final")
        .agg(
            pl.len().alias("transaction_count"),
            pl.col("amount").sum().round(0).alias("total_amount"),
        )
        .rename({"tags_final": "tag"})
        .sort("total_amount", descending=False)  # Largest expenses first (negative)
    )

    # Calculate percentage
    total = result["total_amount"].sum()
    if total != 0:
        result = result.with_columns(
            ((pl.col("total_amount") / total) * 100).round(1).alias("percentage")
        )
    else:
        result = result.with_columns(pl.lit(0.0).alias("percentage"))

    # Limit to top_n (by absolute amount)
    result = result.head(top_n)

    return result


def calculate_top_merchants(
    df: "pl.DataFrame",
    limit: int = 20,
    exclude_transfers: bool = True,
    expense_only: bool = True,
) -> "pl.DataFrame":
    """
    Calculate top merchants by spending.

    Args:
        df: Polars DataFrame with transactions
        limit: Number of top merchants to return (default: 20)
        exclude_transfers: Exclude transfers (default: True)
        expense_only: Only include expense transactions (default: True)

    Returns:
        DataFrame with columns: [merchant, transaction_count, total_amount]
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available")

    if df.is_empty():
        return pl.DataFrame(
            {"merchant": [], "transaction_count": [], "total_amount": []},
            schema={
                "merchant": pl.Utf8,
                "transaction_count": pl.UInt32,
                "total_amount": pl.Float64,
            },
        )

    # Apply filters
    filtered = df
    if exclude_transfers:
        filtered = filtered.filter(exclude_transfers_for(filtered))
    if expense_only:
        filtered = filtered.filter(pl.col("type_norm") == "expense")

    # Filter out null/empty merchants
    filtered = filtered.filter(
        pl.col("merchant_raw").is_not_null() & (pl.col("merchant_raw") != "")
    )

    if filtered.is_empty():
        return pl.DataFrame(
            {"merchant": [], "transaction_count": [], "total_amount": []},
            schema={
                "merchant": pl.Utf8,
                "transaction_count": pl.UInt32,
                "total_amount": pl.Float64,
            },
        )

    # Aggregate by merchant
    result = (
        filtered.group_by("merchant_raw")
        .agg(
            pl.len().alias("transaction_count"),
            pl.col("amount").sum().round(0).alias("total_amount"),
        )
        .rename({"merchant_raw": "merchant"})
        .sort("total_amount", descending=False)  # Largest expenses first (negative)
        .head(limit)
    )

    return result


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
