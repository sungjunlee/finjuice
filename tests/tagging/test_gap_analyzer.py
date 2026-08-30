"""Identity tests for the gap_analyzer mismatch-classification helper split."""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")


def test_mismatch_helpers_live_in_helper_module() -> None:
    """Mismatch classification should not live in the gap orchestration module."""
    analyzer_text = (TAGGING_DIR / "gap_analyzer.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "gap_analyzer_helpers.py").read_text(encoding="utf-8")

    assert "def analyze_tag_category_gaps" in analyzer_text
    assert "def simulate_coverage_improvement" in analyzer_text
    assert "def format_gap_analysis_report" in analyzer_text
    assert "class GapType" in analyzer_text
    assert "class GapAnalysis" in analyzer_text
    assert "class CoverageSimulation" in analyzer_text
    assert "def classify_mismatch" not in analyzer_text
    assert "class MismatchClassification" not in analyzer_text
    assert "def _category_parts" not in analyzer_text
    assert "def _mapped_categories_for_tags" not in analyzer_text
    assert "def classify_mismatch" in helpers_text
    assert "class MismatchClassification" in helpers_text
    assert "def _category_parts" in helpers_text
    assert "def _mapped_categories_for_tags" in helpers_text


def test_mismatch_helpers_reexport_from_gap_analyzer() -> None:
    """Existing gap_analyzer imports should keep resolving to the helpers."""
    analyzer = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer")
    helpers = importlib.import_module("finjuice.pipeline.tagging.gap_analyzer_helpers")

    assert analyzer.MISMATCH_TYPE_CONFLICT is helpers.MISMATCH_TYPE_CONFLICT
    assert analyzer.MISMATCH_TYPE_CATEGORY is helpers.MISMATCH_TYPE_CATEGORY
    assert analyzer.MISMATCH_TYPE_MULTI_TAG_NOISE is helpers.MISMATCH_TYPE_MULTI_TAG_NOISE
    assert analyzer.MISMATCH_SEVERITY_ORDER is helpers.MISMATCH_SEVERITY_ORDER
    assert analyzer.MismatchClassification is helpers.MismatchClassification
    assert analyzer._category_parts is helpers._category_parts
    assert analyzer._mapped_categories_for_tags is helpers._mapped_categories_for_tags
    assert analyzer.classify_mismatch is helpers.classify_mismatch
    assert callable(analyzer.analyze_tag_category_gaps)
    assert callable(analyzer.simulate_coverage_improvement)
    assert callable(analyzer.format_gap_analysis_report)
    assert callable(analyzer.sort_mismatch_gaps)
    assert callable(analyzer.filter_actionable_gaps)
