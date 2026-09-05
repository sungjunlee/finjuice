"""Structure tests for the gap_analyzer.py merchant-analysis helper split.

Gap-type classification, GapAnalysis records, and the analyze/sort/filter
helpers live in ``gap_analyzer_cluster`` and must stay identity-equal when
re-exported from ``gap_analyzer``, so existing import paths and monkeypatches
keep working after the split. The split also keeps ``gap_analyzer_cluster``
as the single canonical home for the moved cluster.
"""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

CLUSTER_NAMES = (
    "GapType",
    "GapAnalysis",
    "sort_mismatch_gaps",
    "filter_actionable_gaps",
    "analyze_tag_category_gaps",
)


def test_gap_analyzer_reexports_analysis_cluster_identity() -> None:
    """Analysis helpers stay on gap_analyzer as re-exports after the split."""
    gap_analyzer = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer")
    cluster = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer_cluster")

    for name in CLUSTER_NAMES:
        assert getattr(gap_analyzer, name) is getattr(cluster, name)

    assert callable(gap_analyzer.simulate_coverage_improvement)
    assert callable(gap_analyzer.format_gap_analysis_report)


def test_gap_analyzer_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in gap_analyzer_cluster."""
    gap_analyzer = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer")
    cluster = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer_cluster")
    canonical = "finjuice.pipeline.tagging.gap_analyzer_cluster"

    for name in CLUSTER_NAMES:
        assert getattr(cluster, name).__module__ == canonical
        assert getattr(gap_analyzer, name).__module__ == canonical

    assert gap_analyzer.CoverageSimulation.__module__ == "finjuice.pipeline.tagging.gap_analyzer"
    assert (
        gap_analyzer.simulate_coverage_improvement.__module__
        == "finjuice.pipeline.tagging.gap_analyzer"
    )
    assert (
        gap_analyzer.format_gap_analysis_report.__module__
        == "finjuice.pipeline.tagging.gap_analyzer"
    )


def test_analysis_helpers_live_in_cluster_module() -> None:
    """Merchant analysis helpers should not live in gap_analyzer.py."""
    analyzer_text = (TAGGING_DIR / "gap_analyzer.py").read_text(encoding="utf-8")
    cluster_text = (TAGGING_DIR / "gap_analyzer_cluster.py").read_text(encoding="utf-8")

    assert "def simulate_coverage_improvement" in analyzer_text
    assert "def format_gap_analysis_report" in analyzer_text
    assert "class CoverageSimulation" in analyzer_text
    assert "class GapType" not in analyzer_text
    assert "class GapAnalysis" not in analyzer_text
    assert "def sort_mismatch_gaps" not in analyzer_text
    assert "def filter_actionable_gaps" not in analyzer_text
    assert "def analyze_tag_category_gaps" not in analyzer_text

    assert "class GapType" in cluster_text
    assert "class GapAnalysis" in cluster_text
    assert "def sort_mismatch_gaps" in cluster_text
    assert "def filter_actionable_gaps" in cluster_text
    assert "def analyze_tag_category_gaps" in cluster_text
    assert "def simulate_coverage_improvement" not in cluster_text
    assert "def format_gap_analysis_report" not in cluster_text
    assert "class CoverageSimulation" not in cluster_text

    for name in CLUSTER_NAMES:
        assert name in analyzer_text
