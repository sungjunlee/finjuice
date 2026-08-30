"""Optional-dependency helpers for the DuckDB analytics layer.

Owns detection of the optional ``duckdb``/``polars`` runtime dependencies and
the shared install-hint constant. Public names stay available from
:mod:`finjuice.pipeline.analytics.duckdb_layer`, which re-exports them so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.analytics.install_hints import DUCKDB_DOCTOR_HINT

DUCKDB_INSTALL_HINT = DUCKDB_DOCTOR_HINT


def detect_analytics_dependencies() -> tuple[bool, Any, Any]:
    """Detect the optional DuckDB/Polars analytics dependencies.

    Returns:
        Tuple of ``(available, duckdb_module, polars_module)``. When the
        optional dependencies are missing, ``available`` is ``False`` and the
        module slots hold ``None`` sentinels.
    """
    try:
        import duckdb
        import polars as pl
    except ImportError:
        return False, None, None
    return True, duckdb, pl
