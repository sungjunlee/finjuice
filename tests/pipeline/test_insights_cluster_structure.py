"""Structure tests for the insights helper splits.

Configured-filter loading, active-filter counting, and on-disk
report_filters.yaml lookup live in ``insights_cluster``. Structural-savings
inference lives in ``insights_structural``. Monthly averages and
top-category rollups stay in ``insights_helpers``. Names stay
identity-equal when re-exported from ``insights``, so existing import
paths and monkeypatches keep working after the splits.
"""

from __future__ import annotations

import importlib
from pathlib import Path

PIPELINE_DIR = Path("src/finjuice/pipeline")

CLUSTER_HELPER_NAMES = (
    "_count_active_filters",
    "_load_configured_report_filters",
    "_load_report_filters",
    "_filter_enabled",
)

STRUCTURAL_HELPER_NAMES = (
    "_calculate_transaction_structural_savings",
    "_summarize_recurring_savings",
    "_load_recurring_savings_summary",
    "_observed_months",
    "_month_from_row",
    "_month_from_value",
    "_matching_structural_tags",
    "_parse_tag_value",
    "_normalize_tag",
    "_coerce_float",
    "_category_label",
)

MONTHLY_HELPER_NAMES = (
    "_calculate_monthly_stats",
    "_calculate_top_categories",
    "_build_category_expr",
    "_exclude_transfer_rows",
)


def test_insights_reexports_cluster_helpers_identity() -> None:
    """Report-filter helpers stay on insights as re-exports after the split."""
    insights = importlib.import_module("finjuice.pipeline.insights")
    cluster = importlib.import_module("finjuice.pipeline.insights_cluster")

    assert insights._count_active_filters is cluster._count_active_filters
    assert insights._load_configured_report_filters is cluster._load_configured_report_filters
    assert insights._load_report_filters is cluster._load_report_filters
    assert insights._filter_enabled is cluster._filter_enabled
    assert insights._REPORT_FILTER_CANDIDATES is cluster._REPORT_FILTER_CANDIDATES
    assert callable(insights.collect_status_snapshot)


def test_insights_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in insights_cluster."""
    cluster = importlib.import_module("finjuice.pipeline.insights_cluster")
    insights = importlib.import_module("finjuice.pipeline.insights")
    canonical = "finjuice.pipeline.insights_cluster"

    assert cluster._count_active_filters.__module__ == canonical
    assert cluster._load_configured_report_filters.__module__ == canonical
    assert cluster._load_report_filters.__module__ == canonical
    assert cluster._filter_enabled.__module__ == canonical
    assert insights._count_active_filters.__module__ == canonical
    assert insights._load_configured_report_filters.__module__ == canonical
    assert insights._load_report_filters.__module__ == canonical
    assert insights._filter_enabled.__module__ == canonical


def test_cluster_helpers_live_in_helper_module() -> None:
    """Report-filter loaders should not live in insights.py."""
    insights_text = (PIPELINE_DIR / "insights.py").read_text(encoding="utf-8")
    cluster_text = (PIPELINE_DIR / "insights_cluster.py").read_text(encoding="utf-8")

    assert "def collect_status_snapshot" in insights_text
    assert "class StatusSnapshot" in insights_text
    assert "def _iter_partition_files" in insights_text
    assert "def _compute_date_range" in insights_text
    assert "def _format_date_range" in insights_text
    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}(" not in insights_text
        assert f"def {name}(" in cluster_text
    assert "def collect_status_snapshot" not in cluster_text
    assert "class StatusSnapshot" not in cluster_text
    assert "def _iter_partition_files" not in cluster_text
    assert "def _compute_date_range" not in cluster_text
    assert "def _format_date_range" not in cluster_text


def test_insights_reexports_structural_helpers_identity() -> None:
    """Structural-savings helpers stay on insights as re-exports after the split."""
    insights = importlib.import_module("finjuice.pipeline.insights")
    structural = importlib.import_module("finjuice.pipeline.insights_structural")

    for name in STRUCTURAL_HELPER_NAMES:
        assert getattr(insights, name) is getattr(structural, name)
    assert insights.StructuralSavingsSource is structural.StructuralSavingsSource
    assert insights.RecurringSavingsSummary is structural.RecurringSavingsSummary
    assert (
        insights.TransactionStructuralSavingsSummary
        is structural.TransactionStructuralSavingsSummary
    )
    assert callable(insights.collect_status_snapshot)


def test_insights_structural_is_the_unique_home_for_moved_helpers() -> None:
    """The structural-savings cluster is defined exactly once, in insights_structural."""
    structural = importlib.import_module("finjuice.pipeline.insights_structural")
    insights = importlib.import_module("finjuice.pipeline.insights")
    canonical = "finjuice.pipeline.insights_structural"

    for name in STRUCTURAL_HELPER_NAMES:
        assert getattr(structural, name).__module__ == canonical
        assert getattr(insights, name).__module__ == canonical


def test_structural_helpers_live_in_structural_module() -> None:
    """Structural-savings inference should not live in monthly-stats helpers."""
    helpers_text = (PIPELINE_DIR / "insights_helpers.py").read_text(encoding="utf-8")
    structural_text = (PIPELINE_DIR / "insights_structural.py").read_text(encoding="utf-8")
    insights_text = (PIPELINE_DIR / "insights.py").read_text(encoding="utf-8")
    cluster_text = (PIPELINE_DIR / "insights_cluster.py").read_text(encoding="utf-8")

    for name in STRUCTURAL_HELPER_NAMES:
        assert f"def {name}(" not in helpers_text
        assert f"def {name}(" not in insights_text
        assert f"def {name}(" not in cluster_text
        assert f"def {name}(" in structural_text
        assert name in insights_text

    for name in MONTHLY_HELPER_NAMES:
        assert f"def {name}(" in helpers_text
        assert f"def {name}(" not in structural_text
        assert f"def {name}(" not in cluster_text
        assert f"def {name}(" not in insights_text

    assert "class MonthlyStats" in helpers_text
    assert "class SnapshotCategory" in helpers_text
    assert "class StructuralSavingsSource" in structural_text
    assert "class RecurringSavingsSummary" in structural_text
    assert "class TransactionStructuralSavingsSummary" in structural_text
    assert "class StructuralSavingsSource" not in helpers_text
    assert "class RecurringSavingsSummary" not in helpers_text
    assert "class TransactionStructuralSavingsSummary" not in helpers_text
    assert "def _load_report_filters(" not in structural_text
    assert "def _count_active_filters(" not in structural_text
    assert "def collect_status_snapshot" not in structural_text
    assert "class StatusSnapshot" not in structural_text
