"""Compute helpers for financial snapshot collection.

Owns monthly averages, structural-savings inference, and top-category rollups.
Snapshot dataclasses and ``collect_status_snapshot`` stay in
:mod:`finjuice.pipeline.insights`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict

import polars as pl

from finjuice.pipeline.filters import exclude_transfers_for
from finjuice.pipeline.goals import (
    GoalsDocument,
    load_goals_file,
    monthly_amount_for_recurring_savings,
)


@dataclass(frozen=True)
class SnapshotCategory:
    """Single category rollup for journal/status snapshots."""

    name: str
    amount: int


class StructuralSavingsSource(TypedDict, total=False):
    """Sanitized structural savings source row for status snapshots."""

    source: str
    label: str
    amount: int
    monthly_amount: int
    frequency: str
    tags: list[str]
    category: str
    transaction_count: int
    months: list[str]
    configured_source: str


class MonthlyStats(TypedDict):
    """Typed monthly aggregation payload."""

    monthly_avg_income: Optional[int]
    monthly_avg_expense: Optional[int]
    savings_rate_3mo: Optional[float]
    residual_savings_rate_3mo: Optional[float]
    monthly_avg_consumption_expense: Optional[int]
    consumption_savings_rate_3mo: Optional[float]
    structural_savings_transaction_monthly_avg: int


class RecurringSavingsSummary(TypedDict):
    """Recurring savings declared in goals.yaml."""

    monthly_amount: int
    sources: list[StructuralSavingsSource]
    tag_aliases: set[str]


class TransactionStructuralSavingsSummary(TypedDict):
    """Structural savings inferred from transaction tags."""

    monthly_amounts: dict[str, int]
    sources: list[StructuralSavingsSource]


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


def _load_recurring_savings_summary(goals_file: Path) -> RecurringSavingsSummary:
    """Load confirmed recurring savings entries from a valid goals.yaml."""
    result = load_goals_file(goals_file)
    if result.document is None or result.problems:
        return {"monthly_amount": 0, "sources": [], "tag_aliases": set()}
    return _summarize_recurring_savings(result.document)


def _summarize_recurring_savings(document: GoalsDocument) -> RecurringSavingsSummary:
    """Convert recurring_savings goals into source rows and tag aliases."""
    entries = document.recurring_savings or []
    sources: list[StructuralSavingsSource] = []
    tag_aliases: set[str] = set()
    monthly_total = 0

    for goal in entries:
        monthly_amount = monthly_amount_for_recurring_savings(goal)
        monthly_total += monthly_amount
        tags = list(goal.tags or [])
        tag_aliases.update(tags)
        row: StructuralSavingsSource = {
            "source": "goals.yaml",
            "label": goal.label,
            "monthly_amount": monthly_amount,
            "amount": goal.amount,
            "frequency": goal.frequency,
            "tags": tags,
        }
        if goal.source and goal.source != "goals.yaml":
            row["configured_source"] = goal.source
        sources.append(row)

    return {"monthly_amount": monthly_total, "sources": sources, "tag_aliases": tag_aliases}


def _calculate_transaction_structural_savings(
    df: pl.DataFrame,
    *,
    tag_aliases: set[str],
) -> TransactionStructuralSavingsSummary:
    """Infer structural savings from expense rows tagged with known savings aliases."""
    if df.is_empty() or "amount" not in df.columns or "date" not in df.columns:
        return {"monthly_amounts": {}, "sources": []}

    alias_map = {_normalize_tag(alias): alias for alias in tag_aliases if alias.strip()}
    groups: dict[tuple[str | None, tuple[str, ...]], dict[str, Any]] = {}
    monthly_amounts: dict[str, int] = {}

    for row in df.iter_rows(named=True):
        amount = _coerce_float(row.get("amount"))
        if amount is None or amount >= 0:
            continue
        month = _month_from_row(row)
        if month is None:
            continue
        matching_tags = _matching_structural_tags(row.get("tags_final"), alias_map)
        if not matching_tags:
            continue

        absolute_amount = int(round(abs(amount)))
        monthly_amounts[month] = monthly_amounts.get(month, 0) + absolute_amount
        category = _category_label(row)
        key = (category, tuple(matching_tags))
        group = groups.setdefault(
            key,
            {
                "amount": 0,
                "transaction_count": 0,
                "months": set(),
                "category": category,
                "tags": matching_tags,
            },
        )
        group["amount"] += absolute_amount
        group["transaction_count"] += 1
        group["months"].add(month)

    source_rows: list[StructuralSavingsSource] = []
    observed_month_count = len(_observed_months(df))
    for group in sorted(groups.values(), key=lambda item: (item["category"] or "", item["tags"])):
        monthly_amount = (
            int(round(group["amount"] / observed_month_count)) if observed_month_count else 0
        )
        source: StructuralSavingsSource = {
            "source": "transactions",
            "label": ", ".join(group["tags"]),
            "amount": int(group["amount"]),
            "monthly_amount": monthly_amount,
            "transaction_count": int(group["transaction_count"]),
            "tags": list(group["tags"]),
            "months": sorted(group["months"]),
        }
        if group["category"]:
            source["category"] = str(group["category"])
        source_rows.append(source)

    return {"monthly_amounts": monthly_amounts, "sources": source_rows}


def _observed_months(df: pl.DataFrame) -> set[str]:
    """Return months represented by rows with usable dates."""
    if "date" not in df.columns:
        return set()
    return {
        month
        for value in df.get_column("date").to_list()
        if (month := _month_from_value(value)) is not None
    }


def _month_from_row(row: dict[str, Any]) -> str | None:
    """Extract YYYY-MM from a transaction row."""
    return _month_from_value(row.get("date"))


def _month_from_value(value: Any) -> str | None:
    """Extract YYYY-MM from a date-like value."""
    if value is None:
        return None
    raw = str(value)
    if len(raw) < 7:
        return None
    return raw[:7]


def _matching_structural_tags(value: Any, alias_map: dict[str, str]) -> list[str]:
    """Return unique structural savings tags matched by aliases."""
    matched: dict[str, str] = {}
    for tag in _parse_tag_value(value):
        normalized = _normalize_tag(tag)
        if normalized in alias_map:
            matched[normalized] = alias_map[normalized]
    return sorted(matched.values(), key=lambda tag: tag.casefold())


def _parse_tag_value(value: Any) -> list[str]:
    """Parse tag arrays stored as lists, JSON strings, or Python-list strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []

    stripped = value.strip()
    if not stripped or stripped in {"[]", "null", "None"}:
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(stripped)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [stripped]


def _normalize_tag(tag: str) -> str:
    """Normalize a tag or alias for matching."""
    return tag.strip().casefold()


def _coerce_float(value: Any) -> float | None:
    """Best-effort numeric coercion for mixed transaction schemas."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category_label(row: dict[str, Any]) -> str | None:
    """Return a sanitized category label without merchant or account details."""
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        value = row.get(column_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


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
