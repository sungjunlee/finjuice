"""Structure tests for the review.py data-loading and next-step helper split.

Partition loaders and next-step cue builders live in ``review_helpers`` and
must stay identity-equal when re-exported from ``review``, so existing import
paths and monkeypatches keep working after the split. The split also keeps
``review_helpers`` as the single canonical home for the moved cluster.
"""

from __future__ import annotations

import importlib
from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "_load_latest_month",
    "_load_all_history",
    "_build_review_next_steps",
)


def test_review_reexports_helper_cluster_identity() -> None:
    """Data-loading and next-step helpers stay on review as re-exports."""
    review = importlib.import_module("finjuice.pipeline.cli.commands.review")
    helpers = importlib.import_module("finjuice.pipeline.cli.commands.review_helpers")

    assert review._load_latest_month is helpers._load_latest_month
    assert review._load_all_history is helpers._load_all_history
    assert review._build_review_next_steps is helpers._build_review_next_steps
    assert callable(review.review_command)


def test_review_helpers_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in review_helpers."""
    helpers = importlib.import_module("finjuice.pipeline.cli.commands.review_helpers")
    canonical = "finjuice.pipeline.cli.commands.review_helpers"

    assert helpers._load_latest_month.__module__ == canonical
    assert helpers._load_all_history.__module__ == canonical
    assert helpers._build_review_next_steps.__module__ == canonical


def test_review_helper_cluster_lives_in_helper_module() -> None:
    """Partition loading and next-step cues should not live in the Typer module."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "review_helpers.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "def review_command" not in helpers_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in review_text
        assert name in review_text
        assert f"def {name}" in helpers_text
