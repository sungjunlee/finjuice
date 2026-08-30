"""Identity tests for the duckdb_layer helper split."""

from pathlib import Path

from finjuice.pipeline.analytics import duckdb_layer, duckdb_layer_helpers

ANALYTICS_DIR = Path("src/finjuice/pipeline/analytics")


def test_transactions_source_helpers_live_in_helper_module() -> None:
    """Transactions-source view SQL helpers should not live in duckdb_layer.py."""
    layer_text = (ANALYTICS_DIR / "duckdb_layer.py").read_text(encoding="utf-8")
    helpers_text = (ANALYTICS_DIR / "duckdb_layer_helpers.py").read_text(encoding="utf-8")

    assert "class DuckDBAnalytics" in layer_text
    assert "def register_transactions_view" in layer_text
    assert "def monthly_spend" in layer_text
    assert "def tag_breakdown" in layer_text
    assert "def _validate_csv_schema" in layer_text
    assert "def _is_transfer_expr" not in layer_text
    assert "def _transfer_group_expr" not in layer_text
    assert "def _transactions_source_projection" not in layer_text
    assert "def _tags_list_expr" not in layer_text
    assert "def _build_transactions_source_sql" not in layer_text
    assert "def _is_transfer_expr" in helpers_text
    assert "def _transfer_group_expr" in helpers_text
    assert "def _transactions_source_projection" in helpers_text
    assert "def _tags_list_expr" in helpers_text
    assert "def _build_transactions_source_sql" in helpers_text


def test_transactions_source_helpers_reexport_from_duckdb_layer() -> None:
    """Existing duckdb_layer imports should keep resolving to the view SQL helpers."""
    assert duckdb_layer._is_transfer_expr is duckdb_layer_helpers._is_transfer_expr
    assert duckdb_layer._transfer_group_expr is duckdb_layer_helpers._transfer_group_expr
    assert (
        duckdb_layer._transactions_source_projection
        is duckdb_layer_helpers._transactions_source_projection
    )
    assert duckdb_layer._tags_list_expr is duckdb_layer_helpers._tags_list_expr
    assert (
        duckdb_layer._build_transactions_source_sql
        is duckdb_layer_helpers._build_transactions_source_sql
    )
    assert callable(duckdb_layer.DuckDBAnalytics)
    assert callable(duckdb_layer.validate_readonly_sql)
    assert callable(duckdb_layer.DuckDBAnalytics.register_transactions_view)
    assert callable(duckdb_layer.DuckDBAnalytics.monthly_spend)
    assert callable(duckdb_layer.DuckDBAnalytics.tag_breakdown)
