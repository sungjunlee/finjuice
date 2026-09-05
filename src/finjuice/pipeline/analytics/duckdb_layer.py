"""DuckDB analytics layer for high-performance aggregations.

This module provides a DuckDB-based analytics layer that integrates with
the existing CSV partition storage via zero-copy Apache Arrow conversion
to Polars DataFrames.

View lifecycle (connection setup, CSV schema validation, and transactions
view registration) lives in
:mod:`finjuice.pipeline.analytics.duckdb_view`. This module keeps the
query API on :class:`DuckDBAnalytics`, a thin subclass of that view type.

Read-only SQL validation helpers live in
:mod:`finjuice.pipeline.analytics.readonly_sql` and are re-exported here so
existing callers can keep importing from this module. Optional-dependency
detection helpers live in
:mod:`finjuice.pipeline.analytics.duckdb_layer_helpers`; the install hint is
re-exported here for the same reason. Transactions-view SQL construction
helpers live in :mod:`finjuice.pipeline.analytics.transactions_view_sql` and
are re-exported here as well.

Performance characteristics:
- Native multi-file CSV reading with parallel scan
- Vectorized SQL execution
- Zero-copy integration with Polars via Arrow
- Workload-dependent performance; benchmark before assuming a speed win

See: https://duckdb.org/docs/guides/python/polars
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import polars as pl

from finjuice.pipeline.analytics.duckdb_layer_helpers import (
    DUCKDB_INSTALL_HINT,
    detect_analytics_dependencies,
)
from finjuice.pipeline.analytics.duckdb_view import DuckDBTransactionsView
from finjuice.pipeline.analytics.readonly_sql import (
    RESTRICTED_KEYWORDS,  # noqa: F401 — re-exported for existing duckdb_layer imports
    RESTRICTED_TABLE_FUNCTIONS,  # noqa: F401 — re-exported for existing duckdb_layer imports
    validate_readonly_sql,
)
from finjuice.pipeline.analytics.transactions_view_sql import (
    build_transactions_source_projection,  # noqa: F401 — re-exported for duckdb_layer imports
    build_transactions_source_sql,  # noqa: F401 — re-exported for duckdb_layer imports
    build_transfer_normalization_exprs,  # noqa: F401 — re-exported for duckdb_layer imports
)
from finjuice.pipeline.filters import exclude_transfers_sql
from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_path_pattern,
)
from finjuice.pipeline.tagging.rules import ReportFilters

DUCKDB_AVAILABLE, duckdb, pl = detect_analytics_dependencies()

logger = logging.getLogger(__name__)


class DuckDBAnalytics(DuckDBTransactionsView):
    """High-performance analytics layer using DuckDB.

    This class provides optimized query methods for dashboard aggregations
    and complex analytics using DuckDB's vectorized SQL execution engine.

    Role Separation (ADR-0006):
    - Analytics/Querying: MUST use this class (DuckDB)
    - Ingestion/ETL: MUST use Polars directly
    - Data Exchange: DuckDB -> Polars via zero-copy Arrow

    Features:
    - Zero-copy Polars DataFrame integration via Apache Arrow
    - Native CSV partition reading (parallel scan)
    - Centralized SQL aggregation queries over CSV partitions
    - In-memory execution (no persistent database)
    - Centralized 'transactions' view with normalized types

    Example:
        >>> from pathlib import Path
        >>> analytics = DuckDBAnalytics(Path("data"))
        >>> df = analytics.monthly_spend(exclude_transfers=True)
        >>> print(df.head())

    Args:
        data_dir: Path to data directory containing transactions/ partitions
        memory_limit: Optional memory limit for DuckDB (e.g., "1GB")

    Raises:
        ImportError: If duckdb package is not installed
    """

    def __init__(
        self,
        data_dir: Path,
        memory_limit: Optional[str] = None,
        report_filters: ReportFilters | None = None,
        require_transactions: bool = True,
    ) -> None:
        if not DUCKDB_AVAILABLE:
            raise ImportError(DUCKDB_INSTALL_HINT)
        super().__init__(
            data_dir,
            memory_limit=memory_limit,
            report_filters=report_filters,
            require_transactions=require_transactions,
        )

    def read_partitions(
        self, pattern: str = "*/*/*.csv", columns: Optional[list[str]] = None
    ) -> "pl.DataFrame":
        """Read CSV partitions into Polars DataFrame via DuckDB.

        This method uses DuckDB's native multi-file CSV reader with parallel
        scan for optimal performance, then converts to Polars via zero-copy
        Apache Arrow.

        Args:
            pattern: Glob pattern for CSV files (default: all partitions)
            columns: Optional list of columns to select (default: all)

        Returns:
            Polars DataFrame with transaction data

        Example:
            >>> # Read all partitions
            >>> df = analytics.read_partitions()
            >>>
            >>> # Read specific month
            >>> df_oct = analytics.read_partitions("2024/10/*.csv")
            >>>
            >>> # Read with column selection
            >>> df_subset = analytics.read_partitions(
            ...     columns=["date", "amount", "merchant_raw"]
            ... )
        """
        csv_path = quote_duckdb_path_pattern(self.partitions_path, pattern)

        # Build SELECT clause
        select_clause = (
            ", ".join(quote_duckdb_identifier(column) for column in columns) if columns else "*"
        )

        # DuckDB's read_csv with auto-detection and parallel scan
        sql = f"""
            SELECT {select_clause}
            FROM read_csv(
                {csv_path},
                auto_detect=true,
                union_by_name=true,
                parallel=true
            )
        """

        logger.debug(f"Reading partitions: {pattern}")

        try:
            # Execute query and convert to Polars (zero-copy via Arrow)
            result: "pl.DataFrame" = self.conn.execute(sql).pl()
            logger.info(f"Loaded {len(result)} transactions from {pattern}")
            return result
        except duckdb.Error as e:
            logger.error(f"Failed to read partitions {pattern}: {e}")
            raise

    def query_readonly(self, sql: str, parameters: object | None = None) -> Any:
        """Validate and execute a read-only SQL query.

        Args:
            sql: Raw SQL string. Must be a single SELECT or WITH query.
            parameters: Optional DuckDB parameter sequence or mapping.

        Returns:
            DuckDB execution handle for callers to fetch rows or convert to Polars.

        Raises:
            ValueError: If SQL violates read-only constraints.
        """
        validate_readonly_sql(sql)
        if parameters is None:
            return self.conn.execute(sql)
        return self.conn.execute(sql, parameters)

    def monthly_spend(
        self, exclude_transfers: bool = True, exclude_income: bool = True
    ) -> "pl.DataFrame":
        """Calculate monthly spending totals (optimized aggregation).

        This method uses DuckDB's vectorized aggregation over the centralized
        transactions view. Measured performance is workload-dependent.

        Args:
            exclude_transfers: Exclude internal transfers (default: True)
            exclude_income: Exclude income transactions (default: True)

        Returns:
            Polars DataFrame with columns: [month, transaction_count, total_amount]
            Sorted by month descending (most recent first)

        Example:
            >>> df = analytics.monthly_spend()
            >>> print(df.head())
            shape: (5, 3)
            ┌─────────┬───────────────────┬──────────────┐
            │ month   ┆ transaction_count ┆ total_amount │
            │ ---     ┆ ---               ┆ ---          │
            │ str     ┆ u32               ┆ f64          │
            ╞═════════╪═══════════════════╪══════════════╡
            │ 2024-10 ┆ 156               ┆ -1234567.89  │
            └─────────┴───────────────────┴──────────────┘
        """
        # Build WHERE clause
        where_conditions = []
        if exclude_transfers:
            where_conditions.append(exclude_transfers_sql())
        if exclude_income:
            where_conditions.append("amount < 0")

        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

        sql = f"""
            SELECT
                substr(CAST(date AS VARCHAR), 1, 7) AS month,
                COUNT(*) AS transaction_count,
                SUM(amount) AS total_amount
            FROM transactions
            {where_clause}
            GROUP BY month
            ORDER BY month DESC
        """

        logger.debug("Calculating monthly spend with DuckDB aggregation")
        result: "pl.DataFrame" = self.conn.execute(sql).pl()
        return result

    def tag_breakdown(self, top_n: int = 10, exclude_transfers: bool = True) -> "pl.DataFrame":
        """Calculate spending breakdown by tag.

        Uses DuckDB's tags_list (VARCHAR[]) column, unmested via LATERAL join.

        Args:
            top_n: Number of top spending tags to return (default: 10)
            exclude_transfers: Exclude internal transfers (default: True)

        Returns:
            Polars DataFrame with columns: [tag, transaction_count, total_amount]
            Sorted by total_amount ascending (largest expenses first)

        Example:
            >>> df = analytics.tag_breakdown(top_n=5)
            >>> print(df.head())
            shape: (5, 3)
            ┌──────────┬───────────────────┬──────────────┐
            │ tag      ┆ transaction_count ┆ total_amount │
            │ ---      ┆ ---               ┆ ---          │
            │ str      ┆ u32               ┆ f64          │
            ╞══════════╪═══════════════════╪══════════════╡
            │ 식비     ┆ 45                ┆ -234567.89   │
            └──────────┴───────────────────┴──────────────┘
        """
        top_n = max(1, min(top_n, 100))
        where_clause = "WHERE amount < 0 AND tags_list IS NOT NULL"
        if exclude_transfers:
            where_clause += f" AND {exclude_transfers_sql()}"

        # SQL uses only internal fragments and a clamped integer limit.
        sql = (
            "SELECT t.tag, COUNT(*) AS transaction_count, SUM(amount) AS total_amount "
            "FROM transactions "
            "CROSS JOIN LATERAL unnest(tags_list) AS t(tag) "
            f"{where_clause} "  # nosec B608
            "GROUP BY t.tag "
            "ORDER BY total_amount ASC "
            f"LIMIT {top_n}"  # nosec B608
        )
        logger.debug(f"Calculating top {top_n} tags with DuckDB unnest")
        result: "pl.DataFrame" = self.conn.execute(sql).pl()
        return result

    def __enter__(self) -> DuckDBAnalytics:
        """Context manager entry."""
        return self
