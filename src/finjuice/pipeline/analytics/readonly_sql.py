"""Read-only SQL validation helpers for DuckDB analytics.

Owns restricted-keyword and table-function checks used before executing
user-supplied DuckDB SQL. Public name ``validate_readonly_sql`` stays
available from :mod:`finjuice.pipeline.analytics.duckdb_layer` and
:mod:`finjuice.pipeline.analytics`.
"""

from __future__ import annotations

import re

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
