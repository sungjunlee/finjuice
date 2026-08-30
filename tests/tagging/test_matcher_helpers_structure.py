"""Identity tests for the matcher leaf condition helper split."""

from pathlib import Path

from finjuice.pipeline.tagging import matcher, matcher_helpers

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")


def test_condition_helpers_live_in_helper_module() -> None:
    """Leaf numeric/text condition helpers should not live in the matcher module."""
    matcher_text = (TAGGING_DIR / "matcher.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "matcher_helpers.py").read_text(encoding="utf-8")

    assert "def _check_numeric_condition" not in matcher_text
    assert "def _check_less_than" not in matcher_text
    assert "def _check_greater_than" not in matcher_text
    assert "def _check_regex" not in matcher_text
    assert "def _check_numeric_condition" in helpers_text
    assert "def _check_less_than" in helpers_text
    assert "def _check_greater_than" in helpers_text
    assert "def _check_regex" in helpers_text

    assert "def _check_pattern_match" in matcher_text
    assert "def _check_condition(" in matcher_text
    assert "def _check_conditions" in matcher_text
    assert "def _get_rule_match" in matcher_text
    assert "def apply_tagging_rules" in matcher_text
    assert "def apply_tagging_rules_v3" in matcher_text


def test_condition_helpers_reexport_from_matcher() -> None:
    """Existing matcher imports should keep resolving to the helper definitions."""
    assert matcher._check_numeric_condition is matcher_helpers._check_numeric_condition
    assert matcher._check_less_than is matcher_helpers._check_less_than
    assert matcher._check_greater_than is matcher_helpers._check_greater_than
    assert matcher._check_regex is matcher_helpers._check_regex
    assert callable(matcher.apply_tagging_rules)
    assert callable(matcher.apply_tagging_rules_v3)
