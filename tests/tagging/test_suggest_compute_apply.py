"""Identity tests for the suggest_compute auto-apply helper split."""

from pathlib import Path

from finjuice.pipeline.tagging import suggest_compute, suggest_compute_apply

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

APPLY_HELPER_NAMES = ("_apply_auto_apply_suggestions",)


def test_suggest_apply_helpers_live_in_sibling_module() -> None:
    """Headless auto-apply helpers should not live in the JSON compute module."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")
    apply_text = (TAGGING_DIR / "suggest_compute_apply.py").read_text(encoding="utf-8")

    assert "def _compute_rules_suggest_json" in compute_text
    assert "def _append_applied_suggestion_audit" in compute_text
    for name in APPLY_HELPER_NAMES:
        assert f"def {name}" not in compute_text
        assert f"def {name}" in apply_text


def test_suggest_apply_helpers_reexport_from_suggest_compute() -> None:
    """Existing suggest_compute imports should keep resolving to the apply helpers."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")

    for name in APPLY_HELPER_NAMES:
        assert name in compute_text
        assert getattr(suggest_compute, name) is getattr(suggest_compute_apply, name)
    assert callable(suggest_compute._compute_rules_suggest_json)
    assert callable(suggest_compute._append_applied_suggestion_audit)
    assert callable(suggest_compute._apply_auto_apply_suggestions)
