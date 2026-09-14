"""SQLite→Polars/Arrow→DuckDB query compatibility for CLI read commands.

Issue #436: existing ``show``/``status``/``query``/``explain``/``template``/
``export`` meanings stay on the CSV column contract while reading one
committed SQLite revision. Compatibility CSV is a derived artifact.
"""

from finjuice.pipeline.query.analytics import open_analytics
from finjuice.pipeline.query.derived import (
    CATEGORY_REPORT_CSV,
    DERIVED_FORMAT,
    MANIFEST_NAME,
    TRANSACTIONS_CSV,
    DerivedBundle,
    DerivedFreshness,
    classify_derived,
    write_derived_outputs,
)
from finjuice.pipeline.query.display import display_row, display_rows, strip_display_sentinels
from finjuice.pipeline.query.errors import QuerySourceError
from finjuice.pipeline.query.snapshot import (
    CALCULATION_POLICY,
    GENERATION_ENV_VAR,
    QuerySnapshot,
    configured_snapshot,
    configured_source_frame,
    distinct_month_count,
    filter_month_frame,
    latest_month_label,
    load_query_snapshot,
    read_month_frame,
    read_transactions_frame,
    resolve_generation_database,
)

__all__ = [
    "CALCULATION_POLICY",
    "CATEGORY_REPORT_CSV",
    "DERIVED_FORMAT",
    "DerivedBundle",
    "DerivedFreshness",
    "GENERATION_ENV_VAR",
    "MANIFEST_NAME",
    "QuerySnapshot",
    "QuerySourceError",
    "TRANSACTIONS_CSV",
    "classify_derived",
    "configured_snapshot",
    "configured_source_frame",
    "display_row",
    "display_rows",
    "distinct_month_count",
    "filter_month_frame",
    "latest_month_label",
    "load_query_snapshot",
    "open_analytics",
    "read_month_frame",
    "read_transactions_frame",
    "resolve_generation_database",
    "strip_display_sentinels",
    "write_derived_outputs",
]
