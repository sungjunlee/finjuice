"""Large recurring-outflow detection used by obligation confirmation."""

from __future__ import annotations

import re
from typing import Any

import polars as pl

from finjuice.pipeline.checkup.models import RecurringOutflowCandidate
from finjuice.pipeline.checkup.partitions import expense_rows
from finjuice.pipeline.checkup.values import float_or_none

_RECURRING_OBLIGATION_MIN_MONTHS = 6
_RECURRING_OBLIGATION_MAX_RELATIVE_RANGE = 0.4
_SENSITIVE_DIGIT_PATTERN = re.compile(r"\d[\d\s-]{3,}\d")


def _detect_large_recurring_outflow_candidates(
    df: pl.DataFrame,
    *,
    threshold_monthly_krw: int,
    known_labels: set[str],
) -> list[RecurringOutflowCandidate]:
    """Return sanitized monthly recurring outflow confirmation candidates."""
    if df.is_empty() or "amount" not in df.columns or "date" not in df.columns:
        return []

    expense_df = expense_rows(df)
    if expense_df.is_empty():
        return []

    groups: dict[str, dict[str, Any]] = {}
    for row in expense_df.to_dicts():
        month = _transaction_month(row.get("date"))
        amount = float_or_none(row.get("amount"))
        label = _recurring_outflow_label(row)
        if month is None or amount is None or amount >= 0 or label is None:
            continue

        key = label.casefold()
        if key in known_labels:
            continue

        group = groups.setdefault(
            key,
            {
                "label": label,
                "month_totals": {},
                "transaction_count": 0,
            },
        )
        month_totals = group["month_totals"]
        month_totals[month] = int(month_totals.get(month, 0) + abs(round(amount)))
        group["transaction_count"] = int(group["transaction_count"]) + 1

    candidates: list[RecurringOutflowCandidate] = []
    for group in groups.values():
        month_totals = group["month_totals"]
        active_months = sorted(month_totals)
        if len(active_months) < _RECURRING_OBLIGATION_MIN_MONTHS:
            continue
        if not _months_are_consecutive(active_months):
            continue

        amounts = [int(month_totals[month]) for month in active_months]
        average_monthly_amount = int(round(sum(amounts) / len(amounts)))
        if average_monthly_amount < threshold_monthly_krw:
            continue

        min_amount = min(amounts)
        max_amount = max(amounts)
        relative_range = (max_amount - min_amount) / max_amount if max_amount else 0
        if relative_range > _RECURRING_OBLIGATION_MAX_RELATIVE_RANGE:
            continue

        label = str(group["label"])
        question = (
            f"{label} 지출이 {len(active_months)}개월 동안 월 "
            f"{_format_won(min_amount)}~{_format_won(max_amount)} 수준으로 반복됩니다. "
            "대출, 월세, 보험료 같은 확정 의무로 known_obligations에 기록할까요?"
        )
        candidates.append(
            RecurringOutflowCandidate(
                label=label,
                cadence="monthly",
                amount_range={"min": min_amount, "max": max_amount},
                average_monthly_amount=average_monthly_amount,
                active_months=active_months,
                active_month_count=len(active_months),
                transaction_count=int(group["transaction_count"]),
                suggested_confirmation_question=question,
            )
        )

    return sorted(
        candidates,
        key=lambda item: (-item.average_monthly_amount, item.label.casefold()),
    )


def _transaction_month(value: Any) -> str | None:
    """Return YYYY-MM from a transaction date-like value."""
    if value is None:
        return None
    raw = str(value)
    if len(raw) < 7:
        return None
    month = raw[:7]
    return month if len(month) == 7 and month[4] == "-" else None


def _recurring_outflow_label(row: dict[str, Any]) -> str | None:
    """Build a sanitized recurring-outflow label without memo/account fields."""
    for column_name in (
        "merchant_raw",
        "category_final",
        "category_rule",
        "minor_raw",
        "major_raw",
    ):
        value = row.get(column_name)
        if value is None:
            continue
        label = _sanitize_recurring_label(str(value))
        if label:
            return label
    return None


def _sanitize_recurring_label(raw_value: str) -> str | None:
    """Remove obvious account-like digit runs and cap labels for JSON surfaces."""
    label = " ".join(raw_value.strip().split())
    if not label:
        return None
    label = _SENSITIVE_DIGIT_PATTERN.sub("#", label)
    label = re.sub(r"\d{4,}", "#", label)
    return label[:40]


def _months_are_consecutive(months: list[str]) -> bool:
    """Return True when month labels form a gapless sequence."""
    ordinals = [_month_ordinal(month) for month in months]
    if any(ordinal is None for ordinal in ordinals):
        return False

    typed_ordinals = [ordinal for ordinal in ordinals if ordinal is not None]
    return typed_ordinals == list(range(typed_ordinals[0], typed_ordinals[0] + len(months)))


def _month_ordinal(month: str) -> int | None:
    """Convert YYYY-MM into a monotonic month ordinal."""
    try:
        year_raw, month_raw = month.split("-", 1)
        year = int(year_raw)
        month_number = int(month_raw)
    except ValueError:
        return None
    if not 1 <= month_number <= 12:
        return None
    return year * 12 + month_number


def _format_won(value: int) -> str:
    """Format a KRW integer for internal question text."""
    return f"₩{value:,}"
