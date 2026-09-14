"""Register trusted detached transaction frames without reading their source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from finjuice.pipeline.analytics.query_builder import build_report_filter_duckdb_where
from finjuice.pipeline.analytics.transactions_view_sql import build_transactions_source_sql
from finjuice.pipeline.tagging.rules import ReportFilters

if TYPE_CHECKING:
    import polars as pl
    from duckdb import DuckDBPyConnection


def register_transaction_frame(
    conn: DuckDBPyConnection, frame: pl.DataFrame, report_filters: ReportFilters
) -> None:
    """Register the normalized analytics views over an already verified frame.

    The caller owns the connection and must close it on success or failure. This
    helper neither selects transaction scope nor verifies source authority; those
    decisions belong to the reader that supplied the detached frame.
    """
    conn.register("_repository_transaction_rows", frame.to_arrow())
    conn.execute(
        "CREATE OR REPLACE VIEW transactions_raw AS "
        f"SELECT {_date_projection(conn)} FROM _repository_transaction_rows"
    )
    columns = [str(row[0]) for row in conn.execute("DESCRIBE transactions_raw").fetchall()]
    conn.execute(build_transactions_source_sql(columns))
    sql = "CREATE OR REPLACE VIEW transactions AS SELECT * FROM transactions_source"
    filter_where = build_report_filter_duckdb_where(report_filters)
    if filter_where:
        sql += f" WHERE NOT ({filter_where})"
    conn.execute(sql)


def _date_projection(conn: DuckDBPyConnection) -> str:
    """Keep valid legacy date columns usable with DuckDB date functions."""
    result = conn.execute(
        "SELECT count(date) > 0 AND count(date) = count(TRY_CAST(date AS DATE)) "
        "FROM _repository_transaction_rows"
    ).fetchone()
    assert result is not None
    if result[0]:
        return "* REPLACE (CAST(date AS DATE) AS date)"
    return "*"
