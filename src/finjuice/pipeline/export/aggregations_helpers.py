"""Table aggregation helpers for multi-format export.

Owns monthly spend, tag breakdown, and top-merchant DataFrame aggregations.
Transaction loading and summary-stat dicts stay in
:mod:`finjuice.pipeline.export.aggregations`, which re-exports these names
so existing callers can keep importing from that module.
"""

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

from finjuice.pipeline.filters import exclude_transfers_for


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
