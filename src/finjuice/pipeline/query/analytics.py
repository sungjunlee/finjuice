"""DuckDB analytics factory that prefers an explicit SQLite source frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.query.snapshot import configured_source_frame
from finjuice.pipeline.tagging.rules import ReportFilters


def open_analytics(
    data_dir: Path,
    memory_limit: str | None = None,
    report_filters: ReportFilters | None = None,
    require_transactions: bool = True,
    source_frame: Any | None = None,
) -> DuckDBAnalytics:
    """Open DuckDB with an explicit frame taking precedence over the locator.

    An explicit ``source_frame`` is the selected authority for this call. The
    generation env var is consulted only when ``source_frame`` is omitted.

    Args:
        data_dir: Data directory used for CSV fallback and DuckDB setup.
        memory_limit: Optional DuckDB memory limit.
        report_filters: Optional report filters applied to the view.
        require_transactions: Whether missing CSV partitions are an error.
            Forced off when a SQLite frame is selected.
        source_frame: Explicit Polars frame. When provided, it is used even if
            a generation locator is also set.

    Returns:
        Connected ``DuckDBAnalytics`` with the ``transactions`` view registered.
    """
    frame = configured_source_frame() if source_frame is None else source_frame
    if frame is not None:
        require_transactions = False
    return DuckDBAnalytics(
        data_dir,
        memory_limit=memory_limit,
        report_filters=report_filters,
        require_transactions=require_transactions,
        source_frame=frame,
    )


__all__ = ["open_analytics"]
