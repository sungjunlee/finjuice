"""Identity tests for the checkup rendering helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands.checkup import rendering, rendering_helpers

CHECKUP_CLI_DIR = Path("src/finjuice/pipeline/cli/commands/checkup")


def test_domain_summary_helpers_live_in_helper_module() -> None:
    """One-line domain summaries should not live in the rendering module."""
    rendering_text = (CHECKUP_CLI_DIR / "rendering.py").read_text(encoding="utf-8")
    helpers_text = (CHECKUP_CLI_DIR / "rendering_helpers.py").read_text(encoding="utf-8")

    assert "def serialize_checkup_payload" in rendering_text
    assert "def serialize_checkup" in rendering_text
    assert "def render_text" in rendering_text
    assert "def _compact_checkup" in rendering_text
    assert "def _summarize_pipeline" not in rendering_text
    assert "def _summarize_review" not in rendering_text
    assert "def _summarize_budget" not in rendering_text
    assert "def _summarize_networth" not in rendering_text
    assert "def _summarize_obligations" not in rendering_text
    assert "def _format_won" not in rendering_text
    assert "def _summarize_pipeline" in helpers_text
    assert "def _summarize_review" in helpers_text
    assert "def _summarize_budget" in helpers_text
    assert "def _summarize_networth" in helpers_text
    assert "def _summarize_obligations" in helpers_text
    assert "def _format_won" in helpers_text


def test_domain_summary_helpers_reexport_from_rendering() -> None:
    """Existing rendering imports should keep resolving to the summary helpers."""
    assert rendering._summarize_pipeline is rendering_helpers._summarize_pipeline
    assert rendering._summarize_review is rendering_helpers._summarize_review
    assert rendering._summarize_budget is rendering_helpers._summarize_budget
    assert rendering._summarize_networth is rendering_helpers._summarize_networth
    assert rendering._summarize_obligations is rendering_helpers._summarize_obligations
    assert rendering._format_won is rendering_helpers._format_won
    assert callable(rendering.serialize_checkup_payload)
    assert callable(rendering.serialize_checkup)
    assert callable(rendering.render_text)
    assert callable(rendering._compact_checkup)
