"""Structure tests for the suggestion_scoring suggested-rule payload split.

Rule-name sanitization, Banksalad category/tag defaults, and
``suggested_rule`` payload construction live in
``suggestion_scoring_cluster`` and must stay identity-equal when re-exported
from ``suggestion_scoring``, so existing import paths and monkeypatches keep
working after the split. Match-pattern helpers stay in
``suggestion_scoring_helpers``. Payment-gateway classification lives in
``suggestion_scoring_classify`` and is identity-reexported from scoring.
Merchant-context assembly stays defined in ``suggestion_scoring``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")
CLUSTER_MODULE = "finjuice.pipeline.tagging.suggestion_scoring_cluster"
SCORING_MODULE = "finjuice.pipeline.tagging.suggestion_scoring"
HELPERS_MODULE = "finjuice.pipeline.tagging.suggestion_scoring_helpers"
CLASSIFY_MODULE = "finjuice.pipeline.tagging.suggestion_scoring_classify"

CLUSTER_HELPER_NAMES = (
    "_banksalad_category_parts",
    "_default_category_from_suggestion",
    "_default_tags_from_suggestion",
    "_deduplicate_rule_name",
    "_sanitize_rule_name",
    "get_suggested_rule_name",
    "build_suggested_rule_field",
)
CLUSTER_CONSTANT_NAMES = (
    "SUGGESTED_RULE_PRIORITY",
    "RECURRING_PRIORITY_BOOST",
)
MATCH_PATTERN_HELPER_NAMES = (
    "_clean_merchant_name",
    "_escape_regex_special_chars",
    "_generate_match_pattern",
)
CLASSIFY_FUNCTION_NAMES = (
    "classify_merchant_kind",
    "is_auto_apply_eligible",
)
CLASSIFY_PRIVATE_FUNCTION_NAMES = ("_normalize_payment_gateway_key",)
CLASSIFY_CONSTANT_NAMES = ("PAYMENT_GATEWAY_AMBIGUOUS_REASON",)
CLASSIFY_PRIVATE_CONSTANT_NAMES = (
    "_KNOWN_PAYMENT_GATEWAY_NORMALIZED",
    "_PAYMENT_GATEWAY_PREFIXES",
)


def test_suggestion_scoring_reexports_payload_cluster_identity() -> None:
    """Suggested-rule payload helpers stay on scoring as re-exports after the split."""
    scoring = importlib.import_module(SCORING_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)
    classify = importlib.import_module(CLASSIFY_MODULE)

    for name in CLUSTER_HELPER_NAMES + CLUSTER_CONSTANT_NAMES:
        assert getattr(scoring, name) is getattr(cluster, name)

    for name in CLASSIFY_FUNCTION_NAMES + CLASSIFY_CONSTANT_NAMES:
        assert getattr(scoring, name) is getattr(classify, name)

    assert callable(scoring.generate_merchant_context)
    assert callable(scoring.classify_merchant_kind)
    assert callable(scoring.is_auto_apply_eligible)


def test_suggestion_scoring_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved payload cluster is defined exactly once, in suggestion_scoring_cluster."""
    scoring = importlib.import_module(SCORING_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)
    classify = importlib.import_module(CLASSIFY_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(scoring, name).__module__ == CLUSTER_MODULE

    for name in CLASSIFY_FUNCTION_NAMES:
        assert getattr(classify, name).__module__ == CLASSIFY_MODULE
        assert getattr(scoring, name).__module__ == CLASSIFY_MODULE

    assert scoring.generate_merchant_context.__module__ == SCORING_MODULE


def test_merchant_kind_classification_does_not_leak_into_scoring() -> None:
    """Classification bodies belong to suggestion_scoring_classify, not scoring."""
    scoring_text = (TAGGING_DIR / "suggestion_scoring.py").read_text(encoding="utf-8")
    classify_text = (TAGGING_DIR / "suggestion_scoring_classify.py").read_text(encoding="utf-8")
    cluster_text = (TAGGING_DIR / "suggestion_scoring_cluster.py").read_text(encoding="utf-8")

    assert "def generate_merchant_context" in scoring_text
    assert "def generate_merchant_context" not in classify_text
    assert "def generate_merchant_context" not in cluster_text

    for name in CLASSIFY_FUNCTION_NAMES + CLASSIFY_PRIVATE_FUNCTION_NAMES:
        assert f"def {name}" not in scoring_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" in classify_text

    for name in CLASSIFY_FUNCTION_NAMES + CLASSIFY_CONSTANT_NAMES:
        assert name in scoring_text

    for name in CLASSIFY_PRIVATE_FUNCTION_NAMES + CLASSIFY_PRIVATE_CONSTANT_NAMES:
        assert name not in scoring_text
        assert name in classify_text

    for name in CLASSIFY_CONSTANT_NAMES:
        assert f"{name} =" not in scoring_text
        assert f"{name} =" in classify_text


def test_payload_cluster_lives_in_cluster_module() -> None:
    """Suggested-rule payloads should not live in the scoring entry module."""
    scoring_text = (TAGGING_DIR / "suggestion_scoring.py").read_text(encoding="utf-8")
    cluster_text = (TAGGING_DIR / "suggestion_scoring_cluster.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "suggestion_scoring_helpers.py").read_text(encoding="utf-8")

    assert "def generate_merchant_context" in scoring_text
    assert "def generate_merchant_context" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in scoring_text
        assert f"def {name}" in cluster_text
        assert name in scoring_text

    for name in CLUSTER_CONSTANT_NAMES:
        assert f"{name} =" not in scoring_text
        assert f"{name} =" in cluster_text
        assert name in scoring_text

    for name in MATCH_PATTERN_HELPER_NAMES:
        assert f"def {name}" not in cluster_text
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in scoring_text
