"""SQL construction helpers for the centralized ``transactions`` view.

Owns the projection and expression building used by
:meth:`DuckDBAnalytics.register_transactions_view` to create the normalized
``transactions_source`` view over the raw CSV partitions. Public names stay
available from :mod:`finjuice.pipeline.analytics.duckdb_layer`, which
re-exports them so existing callers can keep importing from that module.

Note on JSON: DuckDB's JSON support in read_csv can be tricky. We start with
basic normalization.

Issue #185: Complete type normalization. Projection entries are quoted
identifiers from DuckDB's internal ``transactions_raw`` introspection, plus
static expressions over those identifiers.
"""

from __future__ import annotations

from collections.abc import Sequence

from finjuice.pipeline.sql_utils import quote_duckdb_identifier, quote_duckdb_string_literal


def build_transfer_normalization_exprs(source_columns: Sequence[str]) -> tuple[str, str, str]:
    """Build transfer-normalization expressions for detected source columns.

    Args:
        source_columns: Column names introspected from ``transactions_raw``.

    Returns:
        Tuple of ``(is_transfer_expr, transfer_group_expr,
        candidate_default_expr)`` SQL fragments. Missing source columns fall
        back to neutral defaults so downstream projections always resolve.
    """
    source_column_set = set(source_columns)
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
    return is_transfer_expr, transfer_group_expr, candidate_default_expr


def build_transactions_source_projection(source_columns: Sequence[str]) -> list[str]:
    """Build the SELECT projection for the ``transactions_source`` view.

    Passes through detected source columns, normalizing transfer-related
    columns and appending defaults when they are absent.

    Args:
        source_columns: Column names introspected from ``transactions_raw``.

    Returns:
        Ordered projection expressions (without trailing commas).
    """
    _is_transfer_expr, transfer_group_expr, candidate_default_expr = (
        build_transfer_normalization_exprs(source_columns)
    )
    source_column_set = set(source_columns)

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


def build_transactions_source_sql(source_columns: Sequence[str]) -> str:
    """Build the ``CREATE OR REPLACE VIEW transactions_source`` statement.

    Args:
        source_columns: Column names introspected from ``transactions_raw``.

    Returns:
        Complete DDL statement that projects ``transactions_raw`` with
        normalized transfer flags and a ``tags_list`` LIST column.
    """
    is_transfer_expr, transfer_group_expr, _candidate_default_expr = (
        build_transfer_normalization_exprs(source_columns)
    )
    duckdb_varchar_list_type = quote_duckdb_string_literal('["VARCHAR"]')
    tags_list_expr = (
        f"from_json({quote_duckdb_identifier('tags_final')}, {duckdb_varchar_list_type}) "
        "AS tags_list"
    )
    return "\n".join(
        [
            "CREATE OR REPLACE VIEW transactions_source AS",
            "SELECT",
            *(
                f"    {projection},"
                for projection in build_transactions_source_projection(source_columns)
            ),
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
