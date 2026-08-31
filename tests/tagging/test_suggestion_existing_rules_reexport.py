"""Identity regression tests for the suggestion_scoring existing-rule helper split."""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")
HELPERS_MODULE = "finjuice.pipeline.tagging.suggestion_existing_rules"
HELPER_NAMES = (
    "_load_existing_patterns",
    "_load_existing_rule_names",
    "_should_skip_existing_rule",
)


def test_suggestion_scoring_reexports_existing_rule_helpers() -> None:
    """Existing-rule helpers stay importable from suggestion_scoring as the same objects."""
    scoring = importlib.import_module("finjuice.pipeline.tagging.suggestion_scoring")
    helpers = importlib.import_module(HELPERS_MODULE)

    for name in HELPER_NAMES:
        assert getattr(scoring, name) is getattr(helpers, name)


def test_existing_rule_helpers_are_defined_in_helper_module() -> None:
    """Helper definitions belong to suggestion_existing_rules, not suggestion_scoring."""
    helpers = importlib.import_module(HELPERS_MODULE)

    for name in HELPER_NAMES:
        assert getattr(helpers, name).__module__ == HELPERS_MODULE

    scoring_text = (TAGGING_DIR / "suggestion_scoring.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "suggestion_existing_rules.py").read_text(encoding="utf-8")
    for name in HELPER_NAMES:
        assert f"def {name}" not in scoring_text
        assert f"def {name}" in helpers_text


def test_suggestion_scoring_keeps_public_scoring_api() -> None:
    """Scoring, classification, and rule-field API stay defined on suggestion_scoring."""
    scoring = importlib.import_module("finjuice.pipeline.tagging.suggestion_scoring")
    scoring_module = "finjuice.pipeline.tagging.suggestion_scoring"

    for name in (
        "classify_merchant_kind",
        "is_auto_apply_eligible",
        "build_suggested_rule_field",
        "get_suggested_rule_name",
        "generate_merchant_context",
    ):
        target = getattr(scoring, name)
        assert callable(target)
        assert target.__module__ == scoring_module
