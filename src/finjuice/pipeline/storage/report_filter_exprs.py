"""Polars expression builders for the declarative report_filters block.

Extracted from ``csv_partition_polars`` so the storage layer no longer mixes
filter-expression construction with CSV partition CRUD. The filter rule types
(``ExcludedMerchantFilter`` etc.) live in ``tagging.models`` — this module is
purely a Polars adapter on top of those typed rules.
"""

from __future__ import annotations

import re

import polars as pl

from finjuice.pipeline.tagging.models import (
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    ReportFilters,
)


def _merchant_filter_expr(filter_rule: ExcludedMerchantFilter) -> pl.Expr:
    """Build one exclusion expression for an excluded_merchants rule."""
    merchant_expr = pl.col("merchant_raw").cast(pl.Utf8, strict=False).fill_null("")
    date_expr = pl.col("date").cast(pl.Utf8, strict=False)

    if filter_rule.match_type == "contains":
        match_expr = merchant_expr.str.to_lowercase().str.contains(
            filter_rule.pattern.lower(),
            literal=True,
        )
    elif filter_rule.match_type == "exact":
        match_expr = merchant_expr.str.to_lowercase() == filter_rule.pattern.lower()
    else:
        compiled = filter_rule.compiled_pattern or re.compile(filter_rule.pattern, re.IGNORECASE)
        match_expr = merchant_expr.str.contains(f"(?i){compiled.pattern}")

    if filter_rule.since is None:
        return match_expr

    return date_expr.is_not_null() & (date_expr >= filter_rule.since) & match_expr


def _category_filter_expr(filter_rule: ExcludedCategoryFilter) -> pl.Expr:
    """Build one exclusion expression for an excluded_categories rule."""
    return pl.col("category_final").cast(pl.Utf8, strict=False).fill_null("") == filter_rule.name


def _date_range_filter_expr(filter_rule: ExcludedDateRangeFilter) -> pl.Expr:
    """Build one exclusion expression for an excluded_date_ranges rule."""
    date_expr = pl.col("date").cast(pl.Utf8, strict=False)
    return (
        date_expr.is_not_null() & (date_expr >= filter_rule.start) & (date_expr <= filter_rule.end)
    )


def _build_report_filter_rule_exprs(filters: ReportFilters) -> list[pl.Expr]:
    """Build one exclusion expression per configured report filter rule."""
    exprs = [_merchant_filter_expr(filter_rule) for filter_rule in filters.excluded_merchants]
    exprs.extend(_category_filter_expr(filter_rule) for filter_rule in filters.excluded_categories)
    exprs.extend(
        _date_range_filter_expr(filter_rule) for filter_rule in filters.excluded_date_ranges
    )
    return exprs


def build_report_filter_polars_expr(filters: ReportFilters) -> pl.Expr | None:
    """Build a Polars expression that is True for rows excluded by report_filters."""
    exprs = _build_report_filter_rule_exprs(filters)
    if not exprs:
        return None

    combined_expr = exprs[0]
    for expr in exprs[1:]:
        combined_expr = combined_expr | expr
    return combined_expr


def build_filter_expr(filters: ReportFilters) -> pl.Expr | None:
    """Backward-compatible alias for the report filter Polars builder."""
    return build_report_filter_polars_expr(filters)


def matched_report_filter_rule_indexes(df: pl.DataFrame, filters: ReportFilters) -> set[int]:
    """Return indexes of configured report filters that match at least one row."""
    matched_indexes: set[int] = set()
    if df.height == 0 or filters.is_empty():
        return matched_indexes

    for index, expr in enumerate(_build_report_filter_rule_exprs(filters)):
        if df.filter(expr).height > 0:
            matched_indexes.add(index)
    return matched_indexes


__all__ = [
    "build_filter_expr",
    "build_report_filter_polars_expr",
    "matched_report_filter_rule_indexes",
]
