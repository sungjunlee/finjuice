"""Structure checks for the split query_builder helper implementation."""

from pathlib import Path

from finjuice.pipeline.analytics import query_builder, query_builder_helpers

ANALYTICS_DIR = Path("src/finjuice/pipeline/analytics")


def test_report_filter_helpers_live_in_helper_module() -> None:
    """DuckDB report-filter clauses should not live in query_builder.py."""
    query_builder_text = (ANALYTICS_DIR / "query_builder.py").read_text(encoding="utf-8")
    helpers_text = (ANALYTICS_DIR / "query_builder_helpers.py").read_text(encoding="utf-8")

    assert "def build_monthly_spend_query" in query_builder_text
    assert "def build_tag_breakdown_query" in query_builder_text
    assert "def build_top_merchants_query" in query_builder_text
    assert "def build_account_summary_query" in query_builder_text
    assert "def build_date_range_filter_query" in query_builder_text
    assert "def build_recent_spend_movers_query" in query_builder_text
    assert "def _merchant_filter_where_clause" not in query_builder_text
    assert "def _category_filter_where_clause" not in query_builder_text
    assert "def _date_range_filter_where_clause" not in query_builder_text
    assert "def _build_report_filter_duckdb_clauses" not in query_builder_text
    assert "def build_report_filter_duckdb_where" not in query_builder_text
    assert "def build_filter_where_clause" not in query_builder_text
    assert "def _merchant_filter_where_clause" in helpers_text
    assert "def _category_filter_where_clause" in helpers_text
    assert "def _date_range_filter_where_clause" in helpers_text
    assert "def _build_report_filter_duckdb_clauses" in helpers_text
    assert "def build_report_filter_duckdb_where" in helpers_text
    assert "def build_filter_where_clause" in helpers_text


def test_report_filter_helpers_reexport_from_query_builder() -> None:
    """Existing query_builder imports should keep resolving to the filter helpers."""
    assert (
        query_builder._merchant_filter_where_clause
        is query_builder_helpers._merchant_filter_where_clause
    )
    assert (
        query_builder._category_filter_where_clause
        is query_builder_helpers._category_filter_where_clause
    )
    assert (
        query_builder._date_range_filter_where_clause
        is query_builder_helpers._date_range_filter_where_clause
    )
    assert (
        query_builder._build_report_filter_duckdb_clauses
        is query_builder_helpers._build_report_filter_duckdb_clauses
    )
    assert (
        query_builder.build_report_filter_duckdb_where
        is query_builder_helpers.build_report_filter_duckdb_where
    )
    assert (
        query_builder.build_filter_where_clause is query_builder_helpers.build_filter_where_clause
    )
    assert callable(query_builder.build_monthly_spend_query)
    assert callable(query_builder.build_tag_breakdown_query)
    assert callable(query_builder.build_recent_spend_movers_query)
