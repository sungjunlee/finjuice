"""Identity tests for the review payload-shaping helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import review as review_module
from finjuice.pipeline.cli.commands import review_payload

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_review_payload_helpers_live_in_helper_module() -> None:
    """Row sorting, rule notes, and count syncing should not live in the Typer module."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")
    payload_text = (COMMANDS_DIR / "review_payload.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "def _load_review_rule_notes" not in review_text
    assert "def _sort_review_rows" not in review_text
    assert "def _sync_review_page_counts" not in review_text
    assert "def _load_review_rule_notes" in payload_text
    assert "def _sort_review_rows" in payload_text
    assert "def _sync_review_page_counts" in payload_text


def test_review_payload_helpers_reexport_from_entrypoint() -> None:
    """Existing review.py imports should keep resolving to the payload helpers."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "_load_review_rule_notes" in review_text
    assert "_sort_review_rows" in review_text
    assert "_sync_review_page_counts" in review_text
    assert review_module._load_review_rule_notes is review_payload._load_review_rule_notes
    assert review_module._sort_review_rows is review_payload._sort_review_rows
    assert review_module._sync_review_page_counts is review_payload._sync_review_page_counts
    assert callable(review_module.review_command)
