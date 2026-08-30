"""Deterministic calendar and money helpers for net worth forecasting.

Owns month stepping, days-in-month, money rounding, liability-rate
normalization, and CAGR. Projection orchestration, growth, and
lifecycle-event application stay in :mod:`finjuice.pipeline.forecast`,
which re-exports these names so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from datetime import date


def _add_months(start_date: date, months: int) -> date:
    """Return *start_date* shifted by a fixed number of months."""
    month_index = (start_date.month - 1) + months
    year = start_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(start_date.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a calendar month."""
    if month == 2:
        is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if is_leap else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31


def _round_money(value: float) -> float:
    """Round money values to two decimals for deterministic output."""
    return round(value, 2)


def _normalize_liability_rate(raw_rate: float | None) -> float:
    """Normalize liability rates expressed as decimals or human percentages."""
    if raw_rate is None:
        return 0.0
    return raw_rate / 100.0 if abs(raw_rate) > 1.0 else raw_rate


def _calculate_cagr(start_value: float, end_value: float, years: int) -> float | None:
    """Calculate CAGR when the start value is positive."""
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return None
    ratio = end_value / start_value
    return round(float((ratio ** (1.0 / years)) - 1.0), 6)
