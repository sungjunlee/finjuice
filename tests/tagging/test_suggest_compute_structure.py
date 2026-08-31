"""Identity tests for the suggest_compute stats-helper split."""

from pathlib import Path

from finjuice.pipeline.tagging import suggest_compute, suggest_compute_stats

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

STATS_HELPER_NAMES = (
    "_stats_int",
    "_stats_float",
    "_augment_suggestion_stats",
    "_suggest_transfer_exclusions",
    "_rules_suggest_count_payload",
)


def test_suggest_stats_helpers_live_in_sibling_module() -> None:
    """Coverage-stat helpers should not live in the JSON compute module."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")
    stats_text = (TAGGING_DIR / "suggest_compute_stats.py").read_text(encoding="utf-8")

    assert "def _compute_rules_suggest_json" in compute_text
    assert "def _append_applied_suggestion_audit" in compute_text
    assert "TRANSFER_EXCLUSION_DESCRIPTION =" not in compute_text
    for name in STATS_HELPER_NAMES:
        assert f"def {name}" not in compute_text
        assert f"def {name}" in stats_text
    assert "TRANSFER_EXCLUSION_DESCRIPTION =" in stats_text


def test_suggest_stats_helpers_reexport_from_suggest_compute() -> None:
    """Existing suggest_compute imports should keep resolving to the stats helpers."""
    compute_text = (TAGGING_DIR / "suggest_compute.py").read_text(encoding="utf-8")

    for name in STATS_HELPER_NAMES:
        assert name in compute_text
        assert getattr(suggest_compute, name) is getattr(suggest_compute_stats, name)
    assert (
        suggest_compute.TRANSFER_EXCLUSION_DESCRIPTION
        is suggest_compute_stats.TRANSFER_EXCLUSION_DESCRIPTION
    )
    assert callable(suggest_compute._compute_rules_suggest_json)
    assert callable(suggest_compute._compact_rules_suggest_result)
