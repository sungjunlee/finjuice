"""Identity tests for the suggest_compute domain-error helper split."""

from pathlib import Path

from finjuice.pipeline.tagging import suggest_compute, suggest_compute_error

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

ERROR_HELPER_NAMES = (
    "_fail",
)


def test_suggest_error_helpers_live_in_sibling_module() -> None:
    """Domain error helpers should not live in the JSON compute module."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")
    error_text = (TAGGING_DIR / "suggest_compute_error.py").read_text(encoding="utf-8")

    assert "def _compute_rules_suggest_json" in compute_text
    assert "def _append_applied_suggestion_audit" in compute_text
    assert "class SuggestComputeError" not in compute_text
    assert "class SuggestComputeError" in error_text
    for name in ERROR_HELPER_NAMES:
        assert f"def {name}" not in compute_text
        assert f"def {name}" in error_text


def test_suggest_error_helpers_reexport_from_suggest_compute() -> None:
    """Existing suggest_compute imports should keep resolving to the error helpers."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")

    assert "SuggestComputeError" in compute_text
    assert suggest_compute.SuggestComputeError is suggest_compute_error.SuggestComputeError
    for name in ERROR_HELPER_NAMES:
        assert name in compute_text
        assert getattr(suggest_compute, name) is getattr(suggest_compute_error, name)
    assert callable(suggest_compute._compute_rules_suggest_json)
    assert callable(suggest_compute._fail)
