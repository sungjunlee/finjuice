"""Shared DuckDB SQL primitives for analytics query builders.

Owns the trusted ``read_csv`` call construction and non-negative LIMIT
validation used by the public ``build_*`` query builders. Public query
builders stay in :mod:`finjuice.pipeline.analytics.query_builder`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from pathlib import Path

from finjuice.pipeline.sql_utils import quote_duckdb_path_pattern


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
