"""Structure tests for the insights.py report-filter helper split.

Configured-filter loading, active-filter counting, and on-disk
report_filters.yaml lookup live in ``insights_cluster`` and must stay
identity-equal when re-exported from ``insights``, so existing import paths
and monkeypatches keep working after the split. The split also keeps
``insights_cluster`` as the single canonical home for the moved cluster.
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
