"""Pivot SQL builders for template execution.

Owns the dynamic pivot template's axis expressions, month predicates,
column discovery, and bucketed projection builders. Pivot orchestration,
template rendering, audit events, and the run use case stay in
:mod:`finjuice.pipeline.cli.commands.template_cmd.execution`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from finjuice.pipeline.sql_utils import quote_duckdb_identifier

from .param_coercion import _parse_month_start, _quote_sql_literal

PivotAgg = Literal["sum", "avg", "count", "max", "min"]
PivotValue = Literal["amount", "count"]

PIVOT_OTHER_BUCKET = "_other_"
PIVOT_ROW_AXIS_EXPRESSIONS: dict[str, str] = {
    "month": "COALESCE(strftime(date, '%Y-%m'), '_unknown_')",
    "year": "COALESCE(strftime(date, '%Y'), '_unknown_')",
    "quarter": (
        "COALESCE("
        "strftime(date, '%Y') || '-Q' || CAST(date_part('quarter', date) AS VARCHAR), "
        "'_unknown_'"
        ")"
    ),
    "account": "COALESCE(account, '_unknown_')",
    "type_norm": "COALESCE(type_norm, '_unknown_')",
    "is_transfer": "CASE WHEN COALESCE(is_transfer_bool, FALSE) THEN 'true' ELSE 'false' END",
}
PIVOT_COL_AXIS_EXPRESSIONS: dict[str, str] = {
    "category_final": "COALESCE(category_final, '_unknown_')",
    "major_raw": "COALESCE(major_raw, '_unknown_')",
    "minor_raw": "COALESCE(minor_raw, '_unknown_')",
    "merchant_raw": "COALESCE(merchant_raw, '_unknown_')",
    "type_norm": "COALESCE(type_norm, '_unknown_')",
}


def _quote_sql_identifier(value: str) -> str:
    """Return a double-quoted SQL identifier."""
    return quote_duckdb_identifier(value)


def _next_month_start(month_literal: str) -> date:
    """Return the first day of the month after the given YYYY-MM literal."""
    month_start = _parse_month_start(month_literal, param_name="months")
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _build_pivot_months_where(months: str | None) -> str:
    """Build an inclusive month-range predicate for DuckDB DATE rows."""
    if months is None:
        return "TRUE"

    start_month, end_month = months.split(":", 1)
    next_month = _next_month_start(end_month)
    return (
        f"date >= DATE {_quote_sql_literal(f'{start_month}-01')} "
        f"AND date < DATE {_quote_sql_literal(next_month.isoformat())}"
    )


def _normalize_pivot_agg(value: PivotValue, agg: PivotAgg) -> PivotAgg:
    """Resolve `value=count` into the only meaningful aggregate."""
    if value == "count":
        if agg in {"sum", "count"}:
            return "count"
        raise ValueError(
            "Invalid pivot parameters: value=count only supports agg=count "
            "(the default agg=sum is treated as count)."
        )
    return agg


def _build_pivot_base_rows_sql(
    *,
    row: str,
    col: str,
    value: PivotValue,
    months: str | None,
) -> str:
    """Build the normalized base-row SELECT for pivot aggregation."""
    row_expr = PIVOT_ROW_AXIS_EXPRESSIONS[row]
    metric_expr = "1" if value == "count" else "ABS(amount)"
    where_clauses = [_build_pivot_months_where(months)]

    if col == "tags_final":
        where_clauses.append("tags_final IS NOT NULL")
        where_sql = " AND ".join(where_clauses)
        return (
            "SELECT\n"
            f"    {row_expr} AS row_key,\n"
            "    COALESCE(tag, '_unknown_') AS col_key,\n"
            f"    {metric_expr} AS metric_value\n"
            "FROM transactions\n"
            "CROSS JOIN UNNEST(from_json(tags_final, '[\"VARCHAR\"]')) AS tag_list(tag)\n"
            f"WHERE {where_sql}"
        )

    col_expr = PIVOT_COL_AXIS_EXPRESSIONS[col]
    where_sql = " AND ".join(where_clauses)
    return (
        "SELECT\n"
        f"    {row_expr} AS row_key,\n"
        f"    {col_expr} AS col_key,\n"
        f"    {metric_expr} AS metric_value\n"
        "FROM transactions\n"
        f"WHERE {where_sql}"
    )


def _build_pivot_rank_expr(*, value: PivotValue, agg: PivotAgg) -> str:
    """Return the metric used for top-N column discovery."""
    if value == "count" or agg == "count":
        return "COUNT(*)"
    return "SUM(metric_value)"


def _discover_pivot_columns(
    analytics: Any,
    *,
    row: str,
    col: str,
    value: PivotValue,
    agg: PivotAgg,
    months: str | None,
    top_n_cols: int,
) -> tuple[list[str], bool]:
    """Discover deterministic pivot columns and whether `_other_` is needed."""
    base_rows_sql = _build_pivot_base_rows_sql(row=row, col=col, value=value, months=months)
    rank_expr = _build_pivot_rank_expr(value=value, agg=agg)
    discovery_sql = f"""
        WITH base_rows AS (
        {base_rows_sql}
        )
        SELECT col_key
        FROM (
            SELECT
                col_key,
                {rank_expr} AS rank_value
            FROM base_rows
            GROUP BY col_key
        ) ranked_columns
        ORDER BY rank_value DESC, col_key ASC
    """
    discovered_result = analytics.query_readonly(discovery_sql).fetchall()
    discovered = [str(row_value[0]) for row_value in discovered_result]
    return discovered[:top_n_cols], len(discovered) > top_n_cols


def _build_pivot_bucket_case(columns: list[str], include_other_bucket: bool) -> str:
    """Build the column bucketing CASE expression."""
    if not include_other_bucket:
        return "col_key"

    in_list = ", ".join(_quote_sql_literal(column) for column in columns)
    return (
        "CASE\n"
        f"        WHEN col_key IN ({in_list}) THEN col_key\n"
        f"        ELSE {_quote_sql_literal(PIVOT_OTHER_BUCKET)}\n"
        "    END"
    )


def _build_pivot_column_projection(column: str, agg: PivotAgg) -> str:
    """Build one static pivot projection column."""
    column_literal = _quote_sql_literal(column)
    column_alias = _quote_sql_identifier(column)

    if agg == "sum":
        inner = f"SUM(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    elif agg == "avg":
        inner = f"AVG(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    elif agg == "count":
        inner = f"COUNT(CASE WHEN column_bucket = {column_literal} THEN 1 END)"
    elif agg == "max":
        inner = f"MAX(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"
    else:
        inner = f"MIN(CASE WHEN column_bucket = {column_literal} THEN metric_value END)"

    return f"    COALESCE({inner}, 0) AS {column_alias}"
