"""Structural-savings inference for financial snapshot collection.

Owns recurring-savings summaries from goals.yaml, transaction-tag
inference, and the tag/month helpers used only by that cluster.
Snapshot dataclasses and ``collect_status_snapshot`` stay in
:mod:`finjuice.pipeline.insights`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, TypedDict

import polars as pl

from finjuice.pipeline.goals import (
    GoalsDocument,
    load_goals_file,
    monthly_amount_for_recurring_savings,
)


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


class RecurringSavingsSummary(TypedDict):
    """Recurring savings declared in goals.yaml."""

    monthly_amount: int
    sources: list[StructuralSavingsSource]
    tag_aliases: set[str]


class TransactionStructuralSavingsSummary(TypedDict):
    """Structural savings inferred from transaction tags."""

    monthly_amounts: dict[str, int]
    sources: list[StructuralSavingsSource]


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
