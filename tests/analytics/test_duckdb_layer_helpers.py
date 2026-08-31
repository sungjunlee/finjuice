"""Identity coverage for the duckdb_layer optional-dependency helper split."""

from __future__ import annotations

import importlib


def test_duckdb_layer_reexports_optional_dependency_helpers() -> None:
    """Dependency helpers stay importable from duckdb_layer after the split."""
    layer = importlib.import_module("finjuice.pipeline.analytics.duckdb_layer")
    helpers = importlib.import_module("finjuice.pipeline.analytics.duckdb_layer_helpers")

    assert layer.DUCKDB_INSTALL_HINT is helpers.DUCKDB_INSTALL_HINT
    assert layer.detect_analytics_dependencies is helpers.detect_analytics_dependencies
    assert layer.DUCKDB_AVAILABLE is helpers.detect_analytics_dependencies()[0]
    assert callable(layer.DuckDBAnalytics)


def test_helpers_install_hint_matches_doctor_hint() -> None:
    """The shared install hint must remain the doctor hint string."""
    helpers = importlib.import_module("finjuice.pipeline.analytics.duckdb_layer_helpers")
    install_hints = importlib.import_module("finjuice.pipeline.analytics.install_hints")

    assert helpers.DUCKDB_INSTALL_HINT is install_hints.DUCKDB_DOCTOR_HINT
