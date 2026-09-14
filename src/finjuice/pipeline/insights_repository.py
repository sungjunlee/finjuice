"""Detailed insights from detached repository inputs with no external reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import polars as pl
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.goals import load_goals_roundtrip_bytes, validate_goals_payload
from finjuice.pipeline.insights_structural import (
    RecurringSavingsSummary,
    _summarize_recurring_savings,
)
from finjuice.pipeline.tagging.models import ReportFilters

if TYPE_CHECKING:
    from finjuice.pipeline.insights import StatusSnapshotResult


@dataclass(frozen=True)
class RepositoryStatusSnapshotOptions:
    """Pinned configuration and display options for detailed repository status."""

    goals_content: bytes | None
    goals_parsed_status: str | None
    report_filters: ReportFilters
    top_n: int = 5
    active_filter_count: int = 0


_GOALS_WARNING = "Canonical goals could not be interpreted; recurring savings are unavailable."


def _recurring_summary(
    content: bytes | None, status: str | None
) -> tuple[RecurringSavingsSummary, str | None]:
    empty: RecurringSavingsSummary = {"monthly_amount": 0, "sources": [], "tag_aliases": set()}
    if content is None and status is None:
        return empty, None
    if status != "parsed" or content is None:
        return empty, _GOALS_WARNING
    try:
        _, payload = load_goals_roundtrip_bytes(content)
        document, problems = validate_goals_payload(payload)
    except (YAMLError, UnicodeError, ValueError, TypeError):
        return empty, _GOALS_WARNING
    if document is None or problems:
        return empty, _GOALS_WARNING
    return _summarize_recurring_savings(document), None


def _data_range(frame: pl.DataFrame) -> str | None:
    if frame.is_empty() or "date" not in frame.columns:
        return None
    dates = frame.get_column("date").cast(pl.String).drop_nulls()
    if dates.is_empty():
        return None
    first, last = cast(str | None, dates.min()), cast(str | None, dates.max())
    return f"{first} ~ {last}" if first and last else None


def collect_repository_snapshot(
    frame: pl.DataFrame,
    options: RepositoryStatusSnapshotOptions,
) -> StatusSnapshotResult:
    """Apply the legacy compute contract to pinned inputs without loading any files."""
    from finjuice.pipeline.insights import (
        StatusSnapshot,
        StatusSnapshotResult,
        _collect_frame_snapshot,
    )

    recurring, warning = _recurring_summary(options.goals_content, options.goals_parsed_status)
    base = StatusSnapshot(
        data_range=_data_range(frame),
        monthly_avg_income=None,
        monthly_avg_expense=None,
        savings_rate_3mo=None,
        residual_savings_rate_3mo=None,
        monthly_avg_consumption_expense=None,
        consumption_savings_rate_3mo=None,
        structural_savings_monthly_avg=recurring["monthly_amount"],
        structural_savings_transaction_monthly_avg=0,
        recurring_savings_monthly_amount=recurring["monthly_amount"],
        structural_savings_sources=list(recurring["sources"]),
        top_categories=None,
        active_filters=options.active_filter_count,
        active_goals=[],
    )
    computed = _collect_frame_snapshot(
        frame, base, recurring, options.report_filters, options.top_n
    )
    return StatusSnapshotResult(computed.snapshot, warning)
