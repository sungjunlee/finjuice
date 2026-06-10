"""Analytics layer for high-performance aggregations using DuckDB.

This module provides the DuckDB-backed analytics/query engine for SQL-oriented
analytics over CSV partitions. Install the `analytics` extra before using
analytics commands. Performance is workload-dependent; see
`docs/benchmarks/duckdb-results.json` for the current checked-in baseline.

Usage:
    from finjuice.pipeline.analytics import DuckDBAnalytics

    analytics = DuckDBAnalytics(data_dir)
    monthly_df = analytics.monthly_spend()

Install requirements:
    Run `finjuice doctor` for the exact analytics install command
"""

from .duckdb_layer import DuckDBAnalytics, validate_readonly_sql

__all__ = ["DuckDBAnalytics", "validate_readonly_sql"]
