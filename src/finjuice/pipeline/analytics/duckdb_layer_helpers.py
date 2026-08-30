"""Transactions view SQL helpers for DuckDB analytics.

Owns transfer-column expressions, source projections, and the
``transactions_source`` view SQL used by
``DuckDBAnalytics.register_transactions_view``. ``DuckDBAnalytics`` stays
in :mod:`finjuice.pipeline.analytics.duckdb_layer`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from finjuice.pipeline.sql_utils import (
    quote_duckdb_identifier,
    quote_duckdb_string_literal,
)


def _is_transfer_expr(source_column_set: set[str]) -> str:
    """Return the DuckDB expression that normalizes is_transfer to BIGINT."""
    if "is_transfer" in source_column_set:
        return f"TRY_CAST({quote_duckdb_identifier('is_transfer')} AS BIGINT)"
    return "CAST(0 AS BIGINT)"


def _transfer_group_expr(source_column_set: set[str]) -> str:
    """Return the DuckDB expression that normalizes transfer_group_id to VARCHAR."""
    if "transfer_group_id" in source_column_set:
        return f"CAST({quote_duckdb_identifier('transfer_group_id')} AS VARCHAR)"
    return "CAST(NULL AS VARCHAR)"


def _transactions_source_projection(
    source_columns: list[str],
    source_column_set: set[str],
    is_transfer_expr: str,
    transfer_group_expr: str,
) -> list[str]:
    """Return SELECT projection fragments for the transactions_source view."""
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
            f"{candidate_default_expr} AS {quote_duckdb_identifier('is_transfer_candidate')}"
        )
    return source_projection


def _tags_list_expr() -> str:
    """Return the DuckDB expression that parses tags_final JSON into a LIST."""
    duckdb_varchar_list_type = quote_duckdb_string_literal('["VARCHAR"]')
    return (
        f"from_json({quote_duckdb_identifier('tags_final')}, "
        f"{duckdb_varchar_list_type}) AS tags_list"
    )


def _build_transactions_source_sql(source_columns: list[str]) -> str:
    """Build CREATE VIEW SQL that normalizes CSV partitions into transactions_source.

    Projection entries are quoted identifiers from DuckDB's internal
    transactions_raw introspection, plus static expressions over those identifiers.
    """
    source_column_set = set(source_columns)
    is_transfer_expr = _is_transfer_expr(source_column_set)
    transfer_group_expr = _transfer_group_expr(source_column_set)
    source_projection = _transactions_source_projection(
        source_columns,
        source_column_set,
        is_transfer_expr,
        transfer_group_expr,
    )
    tags_list_expr = _tags_list_expr()
    return "\n".join(
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
