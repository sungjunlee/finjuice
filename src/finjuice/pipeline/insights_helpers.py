"""Compute helpers for financial snapshot collection.

Owns monthly averages and top-category rollups. Structural-savings
inference lives in :mod:`finjuice.pipeline.insights_structural`.
Snapshot dataclasses and ``collect_status_snapshot`` stay in
:mod:`finjuice.pipeline.insights`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict

import polars as pl

from finjuice.pipeline.filters import exclude_transfers_for


@dataclass(frozen=True)
class SnapshotCategory:
    """Single category rollup for journal/status snapshots."""

    name: str
    amount: int


class MonthlyStats(TypedDict):
    """Typed monthly aggregation payload."""

    monthly_avg_income: Optional[int]
    monthly_avg_expense: Optional[int]
    savings_rate_3mo: Optional[float]
    residual_savings_rate_3mo: Optional[float]
    monthly_avg_consumption_expense: Optional[int]
    consumption_savings_rate_3mo: Optional[float]
    structural_savings_transaction_monthly_avg: int


def _exclude_transfer_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the shared transfer exclusion rule when possible."""
    return df.filter(exclude_transfers_for(df))


def _calculate_monthly_stats(
    df: pl.DataFrame,
    *,
    structural_monthly_amounts: dict[str, int] | None = None,
) -> MonthlyStats:
    """Compute monthly averages and a recent savings rate."""
    structural_by_month = structural_monthly_amounts or {}
    if df.is_empty() or "date" not in df.columns or "amount" not in df.columns:
        return {
            "monthly_avg_income": None,
            "monthly_avg_expense": None,
            "savings_rate_3mo": None,
            "residual_savings_rate_3mo": None,
            "monthly_avg_consumption_expense": None,
            "consumption_savings_rate_3mo": None,
            "structural_savings_transaction_monthly_avg": 0,
        }

    monthly = (
        df.with_columns(pl.col("date").cast(pl.Utf8).str.slice(0, 7).alias("month"))
        .filter(pl.col("month").is_not_null())
        .group_by("month")
        .agg(
            [
                pl.when(pl.col("amount") > 0)
                .then(pl.col("amount"))
                .otherwise(0.0)
                .sum()
                .alias("income"),
                pl.when(pl.col("amount") < 0)
                .then(pl.col("amount").abs())
                .otherwise(0.0)
                .sum()
                .alias("expense"),
            ]
        )
        .sort("month")
    )

    if monthly.is_empty():
        return {
            "monthly_avg_income": None,
            "monthly_avg_expense": None,
            "savings_rate_3mo": None,
            "residual_savings_rate_3mo": None,
            "monthly_avg_consumption_expense": None,
            "consumption_savings_rate_3mo": None,
            "structural_savings_transaction_monthly_avg": 0,
        }

    avg_income = monthly.select(pl.col("income").mean()).item()
    avg_expense = monthly.select(pl.col("expense").mean()).item()
    monthly_rows = list(monthly.iter_rows(named=True))
    month_count = len(monthly_rows)
    consumption_expense_total = 0.0
    structural_total = 0.0
    for row in monthly_rows:
        month = str(row["month"])
        expense = float(row["expense"] or 0.0)
        structural_amount = min(float(structural_by_month.get(month, 0)), expense)
        structural_total += structural_amount
        consumption_expense_total += max(expense - structural_amount, 0.0)

    recent = monthly.sort("month", descending=True).head(3)
    recent_income = float(recent.select(pl.col("income").sum()).item() or 0.0)
    recent_expense = float(recent.select(pl.col("expense").sum()).item() or 0.0)
    recent_months = [str(month) for month in recent.get_column("month").to_list()]
    recent_structural = sum(structural_by_month.get(month, 0) for month in recent_months)
    recent_consumption_expense = max(recent_expense - recent_structural, 0.0)
    savings_rate = (
        round((recent_income - recent_expense) / recent_income, 2) if recent_income > 0 else None
    )
    consumption_savings_rate = (
        round((recent_income - recent_consumption_expense) / recent_income, 2)
        if recent_income > 0
        else None
    )

    return {
        "monthly_avg_income": int(round(float(avg_income or 0.0))),
        "monthly_avg_expense": int(round(float(avg_expense or 0.0))),
        "savings_rate_3mo": savings_rate,
        "residual_savings_rate_3mo": savings_rate,
        "monthly_avg_consumption_expense": int(
            round(consumption_expense_total / month_count if month_count else 0.0)
        ),
        "consumption_savings_rate_3mo": consumption_savings_rate,
        "structural_savings_transaction_monthly_avg": int(
            round(structural_total / month_count if month_count else 0.0)
        ),
    }


def _calculate_top_categories(df: pl.DataFrame, *, top_n: int) -> list[SnapshotCategory]:
    """Compute top expense categories with schema-compatible fallback order."""
    if df.is_empty() or "amount" not in df.columns:
        return []

    expense_df = df.filter(pl.col("amount") < 0)
    if expense_df.is_empty():
        return []

    category_expr = _build_category_expr(expense_df)
    categories_df = (
        expense_df.with_columns(category_expr.alias("snapshot_category"))
        .group_by("snapshot_category")
        .agg(pl.col("amount").sum().abs().alias("total_amount"))
        .sort("total_amount", descending=True)
        .head(top_n)
    )

    return [
        SnapshotCategory(name=str(row[0]), amount=int(round(float(row[1]))))
        for row in categories_df.iter_rows()
    ]


def _build_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build a fallback category expression for mixed schema versions."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])
