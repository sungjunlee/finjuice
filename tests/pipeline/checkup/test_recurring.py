"""Focused tests for recurring-outflow detection, independent of the composer."""

from __future__ import annotations

import polars as pl

from finjuice.pipeline.checkup.recurring import _detect_large_recurring_outflow_candidates
from tests.pipeline.checkup.helpers import _tx_row, month_labels


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_detect_large_recurring_outflow_candidates_ignores_income_and_transfers() -> None:
    """Income, transfers, and sub-threshold spend must not become candidates."""
    months = month_labels(2025, 4, 8)
    rows: list[dict[str, object]] = []
    for month in months:
        tx_date = f"{month}-05"
        rows.extend(
            [
                _tx_row(
                    tx_date,
                    -250_000.0,
                    "소액구독",
                    category_final="구독",
                    tags_final='["구독"]',
                ),
                _tx_row(
                    tx_date,
                    500_000.0,
                    "급여성입금",
                    category_final="수입",
                    tags_final='["수입"]',
                    type_norm="income",
                    type_raw="입금",
                ),
                _tx_row(
                    tx_date,
                    -700_000.0,
                    "내계좌이체",
                    category_final="이체",
                    tags_final='["이체"]',
                    type_norm="transfer",
                    type_raw="이체",
                    is_transfer=1,
                ),
            ]
        )

    candidates = _detect_large_recurring_outflow_candidates(
        _frame(rows),
        threshold_monthly_krw=300_000,
        known_labels=set(),
    )

    assert candidates == []


def test_detect_large_recurring_outflow_candidates_skips_known_labels() -> None:
    """Labels already recorded as known obligations should be excluded."""
    months = month_labels(2025, 4, 8)
    rows = [
        _tx_row(
            f"{month}-05",
            -450_000.0,
            "주담대",
            category_final="대출",
            tags_final='["대출"]',
        )
        for month in months
    ]

    candidates = _detect_large_recurring_outflow_candidates(
        _frame(rows),
        threshold_monthly_krw=300_000,
        known_labels={"주담대"},
    )

    assert candidates == []


def test_detect_large_recurring_outflow_candidates_requires_consecutive_months() -> None:
    """Irregular (non-consecutive) large outflows should not be confirmation candidates."""
    months = month_labels(2025, 4, 12)
    rows = [
        _tx_row(
            f"{month}-05",
            -520_000.0,
            "불규칙보험",
            category_final="보험",
            tags_final='["보험"]',
        )
        for month in months[::2]
    ]

    candidates = _detect_large_recurring_outflow_candidates(
        _frame(rows),
        threshold_monthly_krw=300_000,
        known_labels=set(),
    )

    assert candidates == []


def test_detect_large_recurring_outflow_candidates_sanitizes_digit_runs() -> None:
    """Account-like digit runs must not leak into candidate labels."""
    months = month_labels(2025, 4, 6)
    rows = [
        _tx_row(
            f"{month}-05",
            -450_000.0,
            "주담대 1234-5678",
            category_final="대출",
            tags_final='["대출"]',
        )
        for month in months
    ]

    candidates = _detect_large_recurring_outflow_candidates(
        _frame(rows),
        threshold_monthly_krw=300_000,
        known_labels=set(),
    )

    assert len(candidates) == 1
    assert candidates[0].label == "주담대 #"
    assert "1234" not in candidates[0].label
    assert candidates[0].cadence == "monthly"
    assert candidates[0].average_monthly_amount == 450_000
    assert candidates[0].active_month_count == 6
