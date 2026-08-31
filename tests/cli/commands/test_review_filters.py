"""Identity tests for the review filter-predicate helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import review as review_module
from finjuice.pipeline.cli.commands import review_filters

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_review_filter_helpers_live_in_helper_module() -> None:
    """Polars filter predicates should not live in the Typer module."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")
    filters_text = (COMMANDS_DIR / "review_filters.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "def _load_latest_month" in review_text
    assert "def _build_review_next_steps" in review_text
    assert "def _is_list_dtype" not in review_text
    assert "def _untagged_expr" not in review_text
    assert "def _tags_present_expr" not in review_text
    assert "def _rule_matched_expr" not in review_text
    assert "def _default_review_expr" not in review_text
    assert "def _count_matches" not in review_text
    assert "def _is_list_dtype" in filters_text
    assert "def _untagged_expr" in filters_text
    assert "def _tags_present_expr" in filters_text
    assert "def _rule_matched_expr" in filters_text
    assert "def _default_review_expr" in filters_text
    assert "def _count_matches" in filters_text


def test_review_filter_helpers_reexport_from_entrypoint() -> None:
    """Existing review.py imports should keep resolving to the filter helpers."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "_is_list_dtype" in review_text
    assert "_untagged_expr" in review_text
    assert "_tags_present_expr" in review_text
    assert "_rule_matched_expr" in review_text
    assert "_default_review_expr" in review_text
    assert "_count_matches" in review_text
    assert review_module._is_list_dtype is review_filters._is_list_dtype
    assert review_module._untagged_expr is review_filters._untagged_expr
    assert review_module._tags_present_expr is review_filters._tags_present_expr
    assert review_module._rule_matched_expr is review_filters._rule_matched_expr
    assert review_module._default_review_expr is review_filters._default_review_expr
    assert review_module._count_matches is review_filters._count_matches
    assert callable(review_module.review_command)
