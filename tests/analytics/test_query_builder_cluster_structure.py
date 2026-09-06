"""Structure tests for the query_builder remaining helper-cluster split.

Trusted ``read_csv`` call construction and LIMIT validation live in
``query_builder_cluster`` and must stay identity-equal when re-exported
from ``query_builder``. Report-filter DuckDB exclusion helpers stay in
``query_builder_helpers``. Public ``build_*`` query builders stay in
``query_builder``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ANALYTICS_DIR = Path("src/finjuice/pipeline/analytics")
CLUSTER_MODULE = "finjuice.pipeline.analytics.query_builder_cluster"
QUERY_MODULE = "finjuice.pipeline.analytics.query_builder"
HELPERS_MODULE = "finjuice.pipeline.analytics.query_builder_helpers"

PUBLIC_BUILDER_NAMES = (
    "build_monthly_spend_query",
    "build_tag_breakdown_query",
    "build_top_merchants_query",
    "build_account_summary_query",
    "build_date_range_filter_query",
    "build_recent_spend_movers_query",
)
CLUSTER_HELPER_NAMES = (
    "_read_csv_call",
    "_validated_limit",
)
HELPERS_NAMES = (
    "_merchant_filter_where_clause",
    "_category_filter_where_clause",
    "_date_range_filter_where_clause",
    "_build_report_filter_duckdb_clauses",
    "build_report_filter_duckdb_where",
    "build_filter_where_clause",
)


def test_query_builder_reexports_cluster_identity() -> None:
    """CSV/LIMIT helpers stay on query_builder as re-exports after the split."""
    query_builder = importlib.import_module(QUERY_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(query_builder, name) is getattr(cluster, name)

    for name in PUBLIC_BUILDER_NAMES:
        assert callable(getattr(query_builder, name))


def test_query_builder_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in query_builder_cluster."""
    query_builder = importlib.import_module(QUERY_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(query_builder, name).__module__ == CLUSTER_MODULE

    for name in PUBLIC_BUILDER_NAMES:
        assert getattr(query_builder, name).__module__ == QUERY_MODULE


def test_cluster_lives_in_cluster_module() -> None:
    """CSV/LIMIT primitives should not live in the public query_builder module."""
    query_text = (ANALYTICS_DIR / "query_builder.py").read_text(encoding="utf-8")
    cluster_text = (ANALYTICS_DIR / "query_builder_cluster.py").read_text(encoding="utf-8")
    helpers_text = (ANALYTICS_DIR / "query_builder_helpers.py").read_text(encoding="utf-8")

    for name in PUBLIC_BUILDER_NAMES:
        assert f"def {name}" in query_text
        assert f"def {name}" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in query_text
        assert f"def {name}" in cluster_text
        assert name in query_text

    for name in HELPERS_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in query_text
