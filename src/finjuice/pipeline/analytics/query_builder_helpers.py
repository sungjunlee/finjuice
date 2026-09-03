"""DuckDB report-filter helpers for analytics query builders.

Owns merchant, category, and date-range exclusion clauses used by
``build_report_filter_duckdb_where``. SQL query builders stay in
:mod:`finjuice.pipeline.analytics.query_builder`, which re-exports these
names so existing callers can keep importing from that module.
"""

from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_string_literal,
)
from finjuice.pipeline.tagging.models import (
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    ReportFilters,
)


def _merchant_filter_where_clause(filter_rule: ExcludedMerchantFilter) -> str:
    """Build one DuckDB exclusion clause for a merchant filter rule."""
    merchant_expr = (
        f"COALESCE(CAST({quote_duckdb_identifier('merchant_raw')} AS VARCHAR), "
        f"{quote_duckdb_string_literal('')})"
    )
    literal = quote_duckdb_string_literal(filter_rule.pattern)

    if filter_rule.match_type == "contains":
        match_clause = f"strpos(lower({merchant_expr}), lower({literal})) > 0"
    elif filter_rule.match_type == "exact":
        match_clause = f"lower({merchant_expr}) = lower({literal})"
    else:
        match_clause = (
            f"regexp_matches({merchant_expr}, {literal}, {quote_duckdb_string_literal('i')})"
        )

    if filter_rule.since is None:
        return f"({match_clause})"

    since_literal = quote_duckdb_string_literal(filter_rule.since)
    return (
        f"({match_clause} AND {quote_duckdb_identifier('date')} IS NOT NULL "
        f"AND CAST({quote_duckdb_identifier('date')} AS VARCHAR) >= {since_literal})"
    )


def _category_filter_where_clause(filter_rule: ExcludedCategoryFilter) -> str:
    """Build one DuckDB exclusion clause for a category filter rule."""
    category = quote_duckdb_string_literal(filter_rule.name)
    category_expr = (
        f"COALESCE(CAST({quote_duckdb_identifier('category_final')} AS VARCHAR), "
        f"{quote_duckdb_string_literal('')})"
    )
    return f"({category_expr} = {category})"


def _date_range_filter_where_clause(filter_rule: ExcludedDateRangeFilter) -> str:
    """Build one DuckDB exclusion clause for a date-range filter rule."""
    start = quote_duckdb_string_literal(filter_rule.start)
    end = quote_duckdb_string_literal(filter_rule.end)
    date_identifier = quote_duckdb_identifier("date")
    return (
        f"({date_identifier} IS NOT NULL "
        f"AND CAST({date_identifier} AS VARCHAR) >= {start} "
        f"AND CAST({date_identifier} AS VARCHAR) <= {end})"
    )


def _build_report_filter_duckdb_clauses(filters: ReportFilters) -> list[str]:
    """Build per-rule DuckDB exclusion clauses from a loaded ReportFilters object."""
    clauses = [
        _merchant_filter_where_clause(filter_rule) for filter_rule in filters.excluded_merchants
    ]
    clauses.extend(
        _category_filter_where_clause(filter_rule) for filter_rule in filters.excluded_categories
    )
    clauses.extend(
        _date_range_filter_where_clause(filter_rule) for filter_rule in filters.excluded_date_ranges
    )
    return clauses


def build_report_filter_duckdb_where(filters: ReportFilters) -> str | None:
    """Build a DuckDB expression that is True for rows excluded by report_filters."""
    clauses = _build_report_filter_duckdb_clauses(filters)
    if not clauses:
        return None
    return " OR ".join(f"({clause})" for clause in clauses)


def build_filter_where_clause(filters: ReportFilters) -> str | None:
    """Backward-compatible alias for the report filter DuckDB builder."""
    return build_report_filter_duckdb_where(filters)
