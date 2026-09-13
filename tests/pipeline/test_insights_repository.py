"""Pinned detailed status never consults live transaction or configuration files."""

from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline import insights
from finjuice.pipeline.tagging.models import ExcludedCategoryFilter, ReportFilters

GOALS = (
    b"version: 1\nmonthly_budget:\n  total: 2000\n  categories: {}\n"
    b"recurring_savings:\n  - label: fixed\n    amount: 100\n"
    b"    frequency: monthly\n    tags: [saving]\n"
)


def _collect(frame: pl.DataFrame, **kwargs):
    return insights.collect_repository_status_snapshot(
        frame, insights.RepositoryStatusSnapshotOptions(**kwargs)
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "amount": [1000.0, -200.0, -100.0],
            "type_norm": ["income", "expense", "expense"],
            "is_transfer": [False, False, False],
            "category_final": ["income", "saved", "food"],
            "tags_final": [[], ["saving"], []],
        }
    )


def test_repository_snapshot_uses_only_frame_goals_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finjuice.pipeline import goals

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live read")

    monkeypatch.setattr(insights, "DuckDBAnalytics", forbidden)
    monkeypatch.setattr(goals, "load_goals_file", forbidden)
    monkeypatch.setattr(pl, "read_csv", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    frame = _frame()
    before = frame.clone()
    result = _collect(
        frame,
        goals_content=GOALS,
        goals_parsed_status="parsed",
        report_filters=ReportFilters(),
        active_filter_count=4,
    )
    assert result.warning is None
    snapshot = result.snapshot
    assert snapshot.data_range == "2026-01-01 ~ 2026-01-03"
    assert snapshot.monthly_avg_income == 1000
    assert snapshot.monthly_avg_expense == 300
    assert snapshot.residual_savings_rate_3mo == 0.7
    assert snapshot.consumption_savings_rate_3mo == 0.9
    assert snapshot.structural_savings_transaction_monthly_avg == 200
    assert snapshot.recurring_savings_monthly_amount == 100
    assert snapshot.structural_savings_monthly_avg == 300
    assert snapshot.active_filters == 4
    assert snapshot.active_goals == []
    assert frame.equals(before)


def test_repository_filters_preserve_unfiltered_date_range() -> None:
    result = _collect(
        _frame(),
        goals_content=None,
        goals_parsed_status=None,
        report_filters=ReportFilters(
            excluded_categories=[ExcludedCategoryFilter(name="food", reason="test")]
        ),
        top_n=1,
        active_filter_count=1,
    )
    assert result.snapshot.monthly_avg_expense == 200
    assert result.snapshot.data_range == "2026-01-01 ~ 2026-01-03"
    assert [item.name for item in result.snapshot.top_categories or []] == ["saved"]


@pytest.mark.parametrize(
    "content,status",
    [
        (b"private: [", "parsed"),
        (GOALS, "invalid"),
        (GOALS, "opaque"),
        (b"version: wrong", "parsed"),
        (None, "parsed"),
    ],
)
def test_invalid_goals_degrade_without_private_warning(content: bytes | None, status: str) -> None:
    result = _collect(
        _frame(),
        goals_content=content,
        goals_parsed_status=status,
        report_filters=ReportFilters(),
    )
    assert (
        result.warning
        == "Canonical goals could not be interpreted; recurring savings are unavailable."
    )
    assert result.snapshot.monthly_avg_expense == 300
    assert result.snapshot.recurring_savings_monthly_amount == 0


def test_empty_repository_keeps_valid_recurring_goals() -> None:
    result = _collect(
        _frame().head(0),
        goals_content=GOALS,
        goals_parsed_status="parsed",
        report_filters=ReportFilters(),
    )
    assert result.snapshot.data_range is None
    assert result.snapshot.monthly_avg_income is None
    assert result.snapshot.top_categories is None
    assert result.snapshot.recurring_savings_monthly_amount == 100
    assert result.warning is None
