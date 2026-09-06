"""Structure tests for the suggestion_format remaining helper-cluster split.

Banksalad category mapping and mapping-guide formatting live in
``suggestion_format_cluster`` and must stay identity-equal when re-exported
from ``suggestion_format``, so existing import paths and monkeypatches keep
working after the split. The public plain-text report and rules.yaml
serialization stay in ``suggestion_format``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")
CLUSTER_MODULE = "finjuice.pipeline.tagging.suggestion_format_cluster"
FORMAT_MODULE = "finjuice.pipeline.tagging.suggestion_format"

PUBLIC_FORMAT_NAMES = (
    "format_suggestions_report",
    "build_rule_dict_from_suggestion",
    "apply_suggestion_to_rules",
)
CLUSTER_HELPER_NAMES = (
    "get_banksalad_category",
    "format_rules_as_banksalad_guide",
    "format_rules_as_markdown",
)
CLUSTER_CONSTANT_NAMES = ("TAG_TO_BANKSALAD_CATEGORY",)


def test_suggestion_format_reexports_cluster_identity() -> None:
    """Banksalad mapping helpers stay on format as re-exports after the split."""
    fmt = importlib.import_module(FORMAT_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES + CLUSTER_CONSTANT_NAMES:
        assert getattr(fmt, name) is getattr(cluster, name)

    for name in PUBLIC_FORMAT_NAMES:
        assert callable(getattr(fmt, name))
    assert callable(fmt._format_suggested_rule_text)


def test_suggestion_format_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved Banksalad cluster is defined exactly once, in the cluster module."""
    fmt = importlib.import_module(FORMAT_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(fmt, name).__module__ == CLUSTER_MODULE

    for name in PUBLIC_FORMAT_NAMES:
        assert getattr(fmt, name).__module__ == FORMAT_MODULE
    assert fmt._format_suggested_rule_text.__module__ == FORMAT_MODULE


def test_banksalad_cluster_lives_in_cluster_module() -> None:
    """Banksalad mapping should not live in the public format entry module."""
    format_text = (TAGGING_DIR / "suggestion_format.py").read_text(encoding="utf-8")
    cluster_text = (TAGGING_DIR / "suggestion_format_cluster.py").read_text(encoding="utf-8")

    assert "def format_suggestions_report" in format_text
    assert "def build_rule_dict_from_suggestion" in format_text
    assert "def apply_suggestion_to_rules" in format_text
    assert "def _format_suggested_rule_text" in format_text
    assert "def format_suggestions_report" not in cluster_text
    assert "def build_rule_dict_from_suggestion" not in cluster_text
    assert "def apply_suggestion_to_rules" not in cluster_text
    assert "def _format_suggested_rule_text" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in format_text
        assert f"def {name}" in cluster_text
        assert name in format_text

    for name in CLUSTER_CONSTANT_NAMES:
        assert f"{name} =" not in format_text
        assert f"{name}: dict[str, str] =" in cluster_text
        assert name in format_text
