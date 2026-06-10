"""Core report-filter application helpers shared by CLI and runtime surfaces.

This module holds the side-effect-free report-filter logic so that non-CLI
core modules (for example ``pipeline.checkup``) can apply report filters
without importing ``finjuice.pipeline.cli.*``. CLI-specific helpers that need
``typer.Context`` or error rendering live in ``finjuice.pipeline.cli.report_filters``.
"""

from __future__ import annotations

import polars as pl

from finjuice.pipeline.storage.report_filter_exprs import (
    build_report_filter_polars_expr,
    matched_report_filter_rule_indexes,
)
from finjuice.pipeline.tagging.models import ReportFilters


def count_matched_report_filters(df: pl.DataFrame, report_filters: ReportFilters) -> int:
    """Return the number of configured filter rules that match at least one row."""
    if df.is_empty() or report_filters.is_empty():
        return 0
    return len(matched_report_filter_rule_indexes(df, report_filters))


def apply_report_filters(
    df: pl.DataFrame,
    report_filters: ReportFilters,
) -> tuple[pl.DataFrame, int]:
    """Filter a DataFrame with report_filters and return the filtered rows plus rule count."""
    filters_applied = count_matched_report_filters(df, report_filters)
    if df.is_empty() or report_filters.is_empty():
        return df, filters_applied

    filter_expr = build_report_filter_polars_expr(report_filters)
    if filter_expr is None:
        return df, filters_applied
    return df.filter(~filter_expr), filters_applied
