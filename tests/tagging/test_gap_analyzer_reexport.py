"""Identity regression tests for the gap_analyzer mismatch-helper split."""

from __future__ import annotations

import importlib


def test_gap_analyzer_reexports_mismatch_classification_helpers() -> None:
    """Mismatch classification helpers stay importable from gap_analyzer."""
    gap_analyzer = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer")
    mismatch = importlib.import_module("finjuice.pipeline.tagging.gap_mismatch")

    for name in (
        "MISMATCH_TYPE_CONFLICT",
        "MISMATCH_TYPE_CATEGORY",
        "MISMATCH_TYPE_MULTI_TAG_NOISE",
        "MISMATCH_SEVERITY_ORDER",
    ):
        assert getattr(gap_analyzer, name) is getattr(mismatch, name)

    assert gap_analyzer.MismatchClassification is mismatch.MismatchClassification
    assert gap_analyzer.classify_mismatch is mismatch.classify_mismatch
    assert gap_analyzer._category_parts is mismatch._category_parts
    assert gap_analyzer._mapped_categories_for_tags is mismatch._mapped_categories_for_tags


def test_gap_analyzer_keeps_public_analysis_api() -> None:
    """Analysis, simulation, and reporting API stay defined on gap_analyzer."""
    gap_analyzer = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer")

    for name in (
        "GapType",
        "GapAnalysis",
        "CoverageSimulation",
        "sort_mismatch_gaps",
        "filter_actionable_gaps",
        "analyze_tag_category_gaps",
        "simulate_coverage_improvement",
        "format_gap_analysis_report",
    ):
        assert getattr(gap_analyzer, name).__module__ == "finjuice.pipeline.tagging.gap_analyzer"
