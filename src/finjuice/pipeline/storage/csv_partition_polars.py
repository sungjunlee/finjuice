"""Compatibility shim for the former Polars CSV partition umbrella module.

The storage implementation now lives in focused modules:

- ``storage.csv_schema`` for schema constants and partition path helpers.
- ``storage.csv_transactions`` for transaction CSV CRUD.
- ``storage.csv_assets`` for asset snapshot CSV CRUD.
- ``storage.report_filter_exprs`` for report-filter Polars expressions.

Only the tiny schema contract remains on this legacy path after the Epic #707
post-release cleanup.
"""

from __future__ import annotations

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS, POLARS_SCHEMA

__all__ = [
    "CSV_COLUMNS",  # Public API — schema contract referenced by external tooling.
    "POLARS_SCHEMA",  # Public API — Polars dtype contract referenced by integrations.
]
