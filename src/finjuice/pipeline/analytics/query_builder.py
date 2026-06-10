"""SQL query builders for DuckDB analytics.

This module provides helper functions to build optimized SQL queries
for common dashboard and analytics operations.

All queries use DuckDB's read_csv() function with:
- auto_detect=true: Automatic schema inference
- union_by_name=true: Handle schema evolution across partitions
- parallel=true: Multi-threaded CSV scanning
"""

from pathlib import Path
from typing import Optional

from finjuice.pipeline.filters import exclude_transfers_sql
from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_path_pattern,
    quote_duckdb_string_literal,
)
from finjuice.pipeline.tagging.models import (
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    ReportFilters,
)


def _read_csv_call(partitions_path: str, data_dir: Path | None = None) -> str:
    """Return the shared trusted DuckDB read_csv call for query builders."""
    base = data_dir if data_dir is not None else Path.cwd()
    path_literal = quote_duckdb_path_pattern(base, partitions_path)
    return (
        "read_csv(\n"
        f"            {path_literal},\n"
        "            auto_detect=true,\n"
        "            union_by_name=true,\n"
        "            parallel=true\n"
        "        )"
    )


def _validated_limit(value: int) -> int:
    """Return a non-negative integer SQL LIMIT value."""
    limit = int(value)
    if limit < 0:
        raise ValueError("SQL LIMIT must be non-negative.")
    return limit


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


def build_monthly_spend_query(
    partitions_path: str,
    exclude_transfers: bool = True,
    exclude_income: bool = True,
    data_dir: Path | None = None,
) -> str:
    """Build SQL query for monthly spending aggregation.

    Args:
        partitions_path: Glob pattern for CSV partitions
        exclude_transfers: Filter out internal transfers (default: True)
        exclude_income: Filter out income transactions (default: True)

    Returns:
        SQL query string

    Example:
        >>> query = build_monthly_spend_query("data/transactions/*/*/*csv")
        >>> print(query)
        SELECT substr(date, 1, 7) AS month, ...
    """
    where_conditions = []
    if exclude_transfers:
        where_conditions.append(exclude_transfers_sql())
    if exclude_income:
        where_conditions.append("amount < 0")

    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    read_csv_call = _read_csv_call(partitions_path, data_dir=data_dir)

    return f"""
        SELECT
            substr(date, 1, 7) AS month,
            COUNT(*) AS transaction_count,
            SUM(amount) AS total_amount
        FROM {read_csv_call}
        {where_clause}
        GROUP BY month
        ORDER BY month DESC
    """


def build_tag_breakdown_query(
    partitions_path: str,
    top_n: int = 10,
    exclude_transfers: bool = True,
    data_dir: Path | None = None,
) -> str:
    """Build SQL query for tag-based spending breakdown.

    Converts CSV-stored tags_final JSON string to VARCHAR[] via from_json(),
    then unmests via LATERAL join.

    Args:
        partitions_path: Glob pattern for CSV partitions
        top_n: Number of top tags to return
        exclude_transfers: Filter out internal transfers (default: True)

    Returns:
        SQL query string

    Example:
        >>> query = build_tag_breakdown_query("data/transactions/*/*/*csv", top_n=5)
    """
    limit = max(1, min(_validated_limit(top_n), 100))
    if exclude_transfers:
        where_clause = f"WHERE {exclude_transfers_sql()} AND amount < 0 AND tags_list IS NOT NULL"
    else:
        where_clause = "WHERE amount < 0 AND tags_list IS NOT NULL"
    read_csv_call = _read_csv_call(partitions_path, data_dir=data_dir)

    return f"""
        WITH src AS (
            SELECT *, from_json(tags_final, '["VARCHAR"]') AS tags_list
            FROM {read_csv_call}
        )
        SELECT t.tag, COUNT(*) AS transaction_count, SUM(amount) AS total_amount
        FROM src
        CROSS JOIN LATERAL unnest(tags_list) AS t(tag)
        {where_clause}
        GROUP BY t.tag
        ORDER BY total_amount ASC
        LIMIT {limit}
    """


def build_top_merchants_query(
    partitions_path: str,
    top_n: int = 10,
    exclude_transfers: bool = True,
    data_dir: Path | None = None,
) -> str:
    """Build SQL query for top merchants by spending.

    Args:
        partitions_path: Glob pattern for CSV partitions
        top_n: Number of top merchants to return
        exclude_transfers: Filter out internal transfers (default: True)

    Returns:
        SQL query string
    """
    limit = _validated_limit(top_n)
    if exclude_transfers:
        where_clause = f"WHERE {exclude_transfers_sql()} AND amount < 0"
    else:
        where_clause = "WHERE amount < 0"
    read_csv_call = _read_csv_call(partitions_path, data_dir=data_dir)

    return f"""
        SELECT
            merchant_raw AS merchant,
            COUNT(*) AS transaction_count,
            SUM(amount) AS total_amount,
            AVG(amount) AS avg_amount
        FROM {read_csv_call}
        {where_clause}
        GROUP BY merchant
        ORDER BY total_amount ASC
        LIMIT {limit}
    """


def build_account_summary_query(
    partitions_path: str,
    exclude_transfers: bool = True,
    data_dir: Path | None = None,
) -> str:
    """Build SQL query for account-wise spending summary.

    Args:
        partitions_path: Glob pattern for CSV partitions
        exclude_transfers: Filter out internal transfers (default: True)

    Returns:
        SQL query string
    """
    where_clause = f"WHERE {exclude_transfers_sql()}" if exclude_transfers else ""
    read_csv_call = _read_csv_call(partitions_path, data_dir=data_dir)

    return f"""
        SELECT
            account,
            COUNT(*) AS transaction_count,
            SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END) AS total_expenses,
            SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS total_income,
            SUM(amount) AS net_amount
        FROM {read_csv_call}
        {where_clause}
        GROUP BY account
        ORDER BY total_expenses ASC
    """


def build_date_range_filter_query(
    partitions_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    columns: Optional[list[str]] = None,
    data_dir: Path | None = None,
) -> str:
    """Build SQL query with date range filtering.

    Args:
        partitions_path: Glob pattern for CSV partitions
        start_date: Start date (YYYY-MM-DD format, inclusive)
        end_date: End date (YYYY-MM-DD format, inclusive)
        columns: Optional list of columns to select (default: all)

    Returns:
        SQL query string

    Example:
        >>> query = build_date_range_filter_query(
        ...     "data/transactions/*/*/*csv",
        ...     start_date="2024-01-01",
        ...     end_date="2024-10-31",
        ...     columns=["date", "amount", "merchant_raw"]
        ... )
    """
    select_clause = (
        ", ".join(quote_duckdb_identifier(column) for column in columns) if columns else "*"
    )

    where_conditions = []
    if start_date:
        where_conditions.append(
            f"{quote_duckdb_identifier('date')} >= {quote_duckdb_string_literal(start_date)}"
        )
    if end_date:
        where_conditions.append(
            f"{quote_duckdb_identifier('date')} <= {quote_duckdb_string_literal(end_date)}"
        )

    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    read_csv_call = _read_csv_call(partitions_path, data_dir=data_dir)

    return f"""
        SELECT {select_clause}
        FROM {read_csv_call}
        {where_clause}
        ORDER BY date DESC, time DESC
    """


def build_recent_spend_movers_query(top_n: int = 5) -> str:
    """Build a 30-day vs previous-30-day spend delta query over the transactions view.

    The query assumes DuckDBAnalytics already registered the shared ``transactions`` view,
    so report_filters and schema normalization come from that layer rather than the CLI.
    """
    limit = _validated_limit(top_n)
    return f"""
        WITH bounds AS (
            SELECT MAX(TRY_CAST(date AS DATE)) AS max_date
            FROM transactions
            WHERE date IS NOT NULL
              AND amount < 0
              AND {exclude_transfers_sql()}
        ),
        windowed AS (
            SELECT
                COALESCE(NULLIF(CAST(category_final AS VARCHAR), ''), '미분류') AS label,
                ROUND(
                    SUM(
                        CASE
                            WHEN txn_date > max_date - INTERVAL 30 DAY
                             AND txn_date <= max_date THEN -amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS recent_spend_krw,
                ROUND(
                    SUM(
                        CASE
                            WHEN txn_date > max_date - INTERVAL 60 DAY
                             AND txn_date <= max_date - INTERVAL 30 DAY THEN -amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS previous_spend_krw
            FROM (
                SELECT
                    TRY_CAST(date AS DATE) AS txn_date,
                    amount,
                    category_final,
                    is_transfer,
                    transfer_group_id
                FROM transactions
            ) AS tx
            CROSS JOIN bounds
            WHERE txn_date IS NOT NULL
              AND amount < 0
              AND {exclude_transfers_sql()}
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                label,
                CAST(recent_spend_krw - previous_spend_krw AS BIGINT) AS delta_krw,
                CASE
                    WHEN recent_spend_krw - previous_spend_krw >= 0 THEN 'up'
                    ELSE 'down'
                END AS direction,
                ABS(recent_spend_krw - previous_spend_krw) AS abs_delta_krw
            FROM windowed
            WHERE recent_spend_krw <> 0 OR previous_spend_krw <> 0
        )
        SELECT
            label,
            delta_krw,
            direction
        FROM ranked
        ORDER BY abs_delta_krw DESC, label
        LIMIT {limit}
    """
