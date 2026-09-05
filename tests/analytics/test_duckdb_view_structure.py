"""Identity and structure coverage for the DuckDB view-lifecycle split."""

from __future__ import annotations

import importlib
from pathlib import Path

ANALYTICS_DIR = Path("src/finjuice/pipeline/analytics")


def test_view_lifecycle_lives_in_view_module() -> None:
    """View register/schema validation should not live in duckdb_layer.py."""
    layer_text = (ANALYTICS_DIR / "duckdb_layer.py").read_text(encoding="utf-8")
    view_text = (ANALYTICS_DIR / "duckdb_view.py").read_text(encoding="utf-8")

    assert "def register_transactions_view" not in layer_text
    assert "def _validate_csv_schema" not in layer_text
    assert "def _view_columns" not in layer_text
    assert "def read_partitions" in layer_text
    assert "def query_readonly" in layer_text
    assert "def monthly_spend" in layer_text
    assert "def tag_breakdown" in layer_text
    assert "class DuckDBAnalytics" in layer_text

    assert "def register_transactions_view" in view_text
    assert "def _validate_csv_schema" in view_text
    assert "def _view_columns" in view_text
    assert "def read_partitions" not in view_text
    assert "def query_readonly" not in view_text
    assert "def monthly_spend" not in view_text
    assert "def tag_breakdown" not in view_text
    assert "class DuckDBTransactionsView" in view_text


def test_duckdb_analytics_is_query_facade_over_view_lifecycle() -> None:
    """DuckDBAnalytics keeps query methods and inherits view lifecycle identity."""
    layer = importlib.import_module("finjuice.pipeline.analytics.duckdb_layer")
    view = importlib.import_module("finjuice.pipeline.analytics.duckdb_view")

    assert issubclass(layer.DuckDBAnalytics, view.DuckDBTransactionsView)
    assert (
        layer.DuckDBAnalytics.register_transactions_view
        is view.DuckDBTransactionsView.register_transactions_view
    )
    assert (
        layer.DuckDBAnalytics._validate_csv_schema
        is view.DuckDBTransactionsView._validate_csv_schema
    )
    assert callable(layer.DuckDBAnalytics.read_partitions)
    assert callable(layer.DuckDBAnalytics.query_readonly)
    assert callable(layer.DuckDBAnalytics.monthly_spend)
    assert callable(layer.DuckDBAnalytics.tag_breakdown)
