"""Identity tests for the suggest_compute compact-helper split."""

from pathlib import Path

from finjuice.pipeline.tagging import suggest_compute, suggest_compute_compact

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

COMPACT_HELPER_NAMES = (
    "_compact_suggested_rule",
    "_compact_rule_suggestion",
    "_compact_rules_suggest_result",
)


def test_suggest_compact_helpers_live_in_sibling_module() -> None:
    """Compact privacy-projection helpers should not live in the JSON compute module."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")
    compact_text = (TAGGING_DIR / "suggest_compute_compact.py").read_text(encoding="utf-8")

    assert "def _compute_rules_suggest_json" in compute_text
    assert "def _append_applied_suggestion_audit" in compute_text
    for name in COMPACT_HELPER_NAMES:
        assert f"def {name}" not in compute_text
        assert f"def {name}" in compact_text


def test_suggest_compact_helpers_reexport_from_suggest_compute() -> None:
    """Existing suggest_compute imports should keep resolving to the compact helpers."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")

    for name in COMPACT_HELPER_NAMES:
        assert name in compute_text
        assert getattr(suggest_compute, name) is getattr(suggest_compute_compact, name)
    assert callable(suggest_compute._compute_rules_suggest_json)
    assert callable(suggest_compute._compact_rules_suggest_result)
