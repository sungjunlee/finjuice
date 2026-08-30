"""Identity tests for the suggestion_scoring match-pattern helper split."""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")


def test_match_pattern_helpers_live_in_helper_module() -> None:
    """Merchant match-pattern generation should not live in suggestion_scoring.py."""
    scoring_text = (TAGGING_DIR / "suggestion_scoring.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "suggestion_scoring_helpers.py").read_text(encoding="utf-8")

    assert "def generate_merchant_context" in scoring_text
    assert "def classify_merchant_kind" in scoring_text
    assert "def build_suggested_rule_field" in scoring_text
    assert "def get_suggested_rule_name" in scoring_text
    assert "def is_auto_apply_eligible" in scoring_text
    assert "def _clean_merchant_name" not in scoring_text
    assert "def _escape_regex_special_chars" not in scoring_text
    assert "def _generate_match_pattern" not in scoring_text
    assert "def _clean_merchant_name" in helpers_text
    assert "def _escape_regex_special_chars" in helpers_text
    assert "def _generate_match_pattern" in helpers_text


def test_match_pattern_helpers_reexport_from_suggestion_scoring() -> None:
    """Existing scoring imports should keep resolving to the match-pattern helpers."""
    scoring = importlib.import_module("finjuice.pipeline.tagging.suggestion_scoring")
    helpers = importlib.import_module("finjuice.pipeline.tagging.suggestion_scoring_helpers")

    assert scoring._clean_merchant_name is helpers._clean_merchant_name
    assert scoring._escape_regex_special_chars is helpers._escape_regex_special_chars
    assert scoring._generate_match_pattern is helpers._generate_match_pattern
    assert callable(scoring.generate_merchant_context)
    assert callable(scoring.classify_merchant_kind)
    assert callable(scoring.build_suggested_rule_field)
    assert callable(scoring.get_suggested_rule_name)
    assert callable(scoring.is_auto_apply_eligible)
