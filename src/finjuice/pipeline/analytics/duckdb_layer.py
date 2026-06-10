"""DuckDB analytics layer for high-performance aggregations.

This module provides a DuckDB-based analytics layer that integrates with
the existing CSV partition storage via zero-copy Apache Arrow conversion
to Polars DataFrames.

Performance characteristics:
- Native multi-file CSV reading with parallel scan
- Vectorized SQL execution
- Zero-copy integration with Polars via Arrow
- Workload-dependent performance; benchmark before assuming a speed win

See: https://duckdb.org/docs/guides/python/polars
"""

import logging
import re
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

from finjuice.pipeline.analytics.install_hints import DUCKDB_DOCTOR_HINT
from finjuice.pipeline.analytics.query_builder import build_report_filter_duckdb_where
from finjuice.pipeline.filters import exclude_transfers_sql
from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_path_pattern,
    quote_duckdb_string_literal,
)
from finjuice.pipeline.storage.schema_registry import get_current_schema
from finjuice.pipeline.tagging.rules import ReportFilters

try:
    import duckdb
    import polars as pl

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    duckdb = None  # type: ignore[assignment]  # optional dependency sentinel
    pl = None  # type: ignore[assignment]  # optional dependency sentinel

logger = logging.getLogger(__name__)
DUCKDB_INSTALL_HINT = DUCKDB_DOCTOR_HINT

RESTRICTED_KEYWORDS = [
    "DELETE",
    "DROP",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "COPY",
    "READ_CSV",
    "READ_PARQUET",
    "READ_JSON",
    "READ_BLOB",
    "INSTALL",
    "LOAD",
]

RESTRICTED_TABLE_FUNCTIONS = [
    "READ_BLOB",
    "READ_CSV",
    "READ_CSV_AUTO",
    "READ_JSON",
    "READ_JSON_AUTO",
    "READ_JSON_OBJECTS",
    "READ_JSON_OBJECTS_AUTO",
    "READ_NDJSON",
    "READ_NDJSON_AUTO",
    "READ_NDJSON_OBJECTS",
    "READ_PARQUET",
    "READ_TEXT",
    "PARQUET_BLOOM_PROBE",
    "PARQUET_FILE_METADATA",
    "PARQUET_KV_METADATA",
    "PARQUET_METADATA",
    "PARQUET_SCAN",
    "PARQUET_SCHEMA",
    "SNIFF_CSV",
]


def _contains_restricted_keyword(sql_upper: str, keyword: str) -> bool:
    """Return True when restricted keyword appears as a standalone SQL token."""
    pattern = rf"(?<![A-Z0-9_]){re.escape(keyword)}(?![A-Z0-9_])"
    return re.search(pattern, sql_upper) is not None


def _contains_restricted_table_function(sql_upper: str, function_name: str) -> bool:
    """Return True when a restricted DuckDB table function is called."""
    pattern = rf"(?<![A-Z0-9_]){re.escape(function_name)}\s*\("
    return re.search(pattern, sql_upper) is not None


def validate_readonly_sql(sql: str) -> str:
    """Validate SQL string for read-only query execution.

    Args:
        sql: Raw SQL string.

    Returns:
        Normalized SQL string (uppercased) for downstream checks.

    Raises:
        ValueError: If SQL violates read-only constraints.
    """
    if ";" in sql.rstrip(";\n\r\t "):
        raise ValueError("Multi-statement queries are not allowed (semicolons detected).")

    normalized_sql = sql.strip().upper()
    if not (normalized_sql.startswith("SELECT") or normalized_sql.startswith("WITH")):
        raise ValueError("Only SELECT or WITH queries are allowed.")

    for function_name in RESTRICTED_TABLE_FUNCTIONS:
        if _contains_restricted_table_function(normalized_sql, function_name):
            raise ValueError(
                "Security violation: Query calls restricted DuckDB table function "
                f"'{function_name}'."
            )

    for keyword in RESTRICTED_KEYWORDS:
        if _contains_restricted_keyword(normalized_sql, keyword):
            raise ValueError(f"Security violation: Query contains restricted keyword '{keyword}'.")

    return normalized_sql


class DuckDBAnalytics:
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

        self.data_dir = Path(data_dir)
        self.partitions_path = self.data_dir / "transactions"
        self.report_filters = report_filters or ReportFilters()

        # Create in-memory connection for speed
        self.conn = duckdb.connect(":memory:")
        self.conn.execute("SET enable_progress_bar=false")

        # Configure memory limit if specified
        if memory_limit:
            self.conn.execute(f"SET memory_limit={quote_duckdb_string_literal(memory_limit)}")

        # DuckDB uses all available cores by default, no need to configure

        self.register_transactions_view(require_transactions=require_transactions)

        logger.info(
            "DuckDB analytics layer initialized (threads: auto, memory: %s)",
            memory_limit or "unlimited",
        )

    def register_transactions_view(self, *, require_transactions: bool = True) -> None:
        """Create centralized transactions view with type normalization (Issue #184).

        This view abstracts the underlying CSV partitions and provides
        normalized types (e.g., boolean flags) to simplify downstream queries.

        Raises:
            FileNotFoundError: If no transaction CSV files are found.
            RuntimeError: If view creation fails.
        """
        # Check if any CSV files exist
        has_files = any(self.partitions_path.glob("*/*/*.csv"))
        if not has_files:
            if not require_transactions:
                logger.debug(
                    "No transaction CSV files found; skipping transaction view registration"
                )
                return
            raise FileNotFoundError(f"No transaction data found in {self.partitions_path}")

        csv_path_literal = quote_duckdb_path_pattern(self.partitions_path)

        raw_sql = f"""
            CREATE OR REPLACE VIEW transactions_raw AS
            SELECT *
            FROM read_csv(
                {csv_path_literal},
                auto_detect=true,
                union_by_name=true,
                parallel=true
            )
        """
        try:
            self.conn.execute(raw_sql)
            source_columns = self._view_columns("transactions_raw")
            source_column_set = set(source_columns)

            self._validate_csv_schema(source_columns)

            is_transfer_expr = (
                f"TRY_CAST({quote_duckdb_identifier('is_transfer')} AS BIGINT)"
                if "is_transfer" in source_column_set
                else "CAST(0 AS BIGINT)"
            )
            transfer_group_expr = (
                f"CAST({quote_duckdb_identifier('transfer_group_id')} AS VARCHAR)"
                if "transfer_group_id" in source_column_set
                else "CAST(NULL AS VARCHAR)"
            )
            candidate_default_expr = f"COALESCE({is_transfer_expr}, 0)"

            source_projection = []
            for column in source_columns:
                quoted_column = quote_duckdb_identifier(column)
                if column == "transfer_group_id":
                    source_projection.append(f"{transfer_group_expr} AS {quoted_column}")
                elif column == "is_transfer_candidate":
                    source_projection.append(
                        "COALESCE("
                        f"TRY_CAST({quoted_column} AS BIGINT), {candidate_default_expr}"
                        f") AS {quoted_column}"
                    )
                else:
                    source_projection.append(quoted_column)

            if "transfer_group_id" not in source_column_set:
                source_projection.append(
                    f"{transfer_group_expr} AS {quote_duckdb_identifier('transfer_group_id')}"
                )
            if "is_transfer_candidate" not in source_column_set:
                source_projection.append(
                    f"{candidate_default_expr} AS "
                    f"{quote_duckdb_identifier('is_transfer_candidate')}"
                )

            # Note on JSON: DuckDB's JSON support in read_csv can be tricky.
            # We start with basic normalization.
            # Issue #185: Complete type normalization
            # Projection entries are quoted identifiers from DuckDB's internal
            # transactions_raw introspection, plus static expressions over those identifiers.
            duckdb_varchar_list_type = quote_duckdb_string_literal('["VARCHAR"]')
            tags_list_expr = (
                f"from_json({quote_duckdb_identifier('tags_final')}, "
                f"{duckdb_varchar_list_type}) AS tags_list"
            )
            source_sql = "\n".join(
                [
                    "CREATE OR REPLACE VIEW transactions_source AS",
                    "SELECT",
                    *(f"    {projection}," for projection in source_projection),
                    "    (",
                    f"        COALESCE({is_transfer_expr}, 0) = 1",
                    f"        AND {transfer_group_expr} IS NOT NULL",
                    f"        AND TRIM({transfer_group_expr}) <> ''",
                    "    ) AS is_transfer_bool,",
                    "    -- Convert JSON string to DuckDB LIST",
                    f"    {tags_list_expr}",
                    "FROM transactions_raw",
                ]
            )
            self.conn.execute(source_sql)
            filter_where = build_report_filter_duckdb_where(self.report_filters)
            view_sql = "CREATE OR REPLACE VIEW transactions AS SELECT * FROM transactions_source"
            if filter_where:
                view_sql += f" WHERE NOT ({filter_where})"
            self.conn.execute(view_sql)
            logger.debug("Created 'transactions' view in DuckDB")
        except duckdb.Error as e:
            logger.error(f"Failed to create transactions view: {e}")
            raise RuntimeError(f"Failed to create transactions view: {e}") from e

    def _validate_csv_schema(self, detected_columns: list[str]) -> None:
        """Validate detected CSV columns against the expected schema.

        Checks for critical missing columns and unexpected columns that may
        indicate data corruption or malicious CSV injection.

        Args:
            detected_columns: Column names detected by DuckDB read_csv.
        """
        try:
            metadata_dir = self.data_dir / "metadata"
            schema = get_current_schema(metadata_dir)
            expected_columns = [col["name"] for col in schema["partition_schema"]["columns"]]
        except Exception:
            logger.debug("Could not load schema registry; skipping CSV schema validation")
            return

        detected_set = set(detected_columns)
        expected_set = set(expected_columns)

        critical_columns = {"row_hash", "date", "amount", "datetime", "file_id", "source_row"}
        missing_critical = critical_columns - detected_set
        if missing_critical:
            logger.warning(
                "CSV schema validation: missing critical columns: %s",
                ", ".join(sorted(missing_critical)),
            )

        extra_columns = detected_set - expected_set
        if extra_columns:
            logger.warning(
                "CSV schema validation: unexpected columns detected: %s",
                ", ".join(sorted(extra_columns)),
            )

    def _view_columns(self, view_name: str) -> list[str]:
        """Return column names for an internal DuckDB view."""
        rows = self.conn.execute(f"DESCRIBE {quote_duckdb_identifier(view_name)}").fetchall()
        return [str(row[0]) for row in rows]

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
        return self.conn.execute(sql).pl()

    def __enter__(self) -> "DuckDBAnalytics":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - close connection."""
        self.close()

    def close(self) -> None:
        """Close DuckDB connection and free resources."""
        if self.conn:
            self.conn.close()
            logger.info("DuckDB connection closed")
