"""Structure checks for the split review command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import review as review_module
from finjuice.pipeline.cli.commands import review_rendering, review_serialize

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_review_rendering_helpers_live_in_helper_module() -> None:
    """KRW/confidence formatting and the review table should not live in the Typer module."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "review_rendering.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "def _format_amount" not in review_text
    assert "def _format_confidence" not in review_text
    assert "def _render_review" not in review_text
    assert "def _format_amount" in rendering_text
    assert "def _format_confidence" in rendering_text
    assert "def _render_review" in rendering_text


def test_review_public_names_stay_on_entrypoint() -> None:
    """The stable review import path should keep the command and extracted helper names."""
    review_text = (COMMANDS_DIR / "review.py").read_text(encoding="utf-8")

    assert "def review_command" in review_text
    assert "_render_review" in review_text
    assert "_format_amount" in review_text
    assert "_format_confidence" in review_text
    assert "_serialize_transaction" in review_text
    assert "_compact_review_result" in review_text
    assert review_module._render_review is review_rendering._render_review
    assert review_module._format_amount is review_rendering._format_amount
    assert review_module._format_confidence is review_rendering._format_confidence
    assert review_module._serialize_transaction is review_serialize._serialize_transaction
    assert review_module._compact_review_result is review_serialize._compact_review_result
    assert callable(review_module.review_command)
