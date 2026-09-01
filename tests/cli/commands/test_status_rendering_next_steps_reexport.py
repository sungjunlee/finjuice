"""Identity checks for the status rendering next-step helper split."""

from __future__ import annotations

import importlib
from pathlib import Path

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")

MOVED_HELPER_NAMES = (
    "_render_status_footnotes",
    "_render_next_steps",
)


def test_next_step_helpers_live_in_helper_module() -> None:
    """Footnote and next-step helpers should not live in rendering.py."""
    rendering_text = (STATUS_DIR / "rendering.py").read_text(encoding="utf-8")
    helpers_text = (STATUS_DIR / "rendering_next_steps.py").read_text(encoding="utf-8")

    assert "def build_status_result" in rendering_text
    assert "def emit_status_result" in rendering_text
    assert "def render_status" in rendering_text
    assert "TAGGING_TERMINOLOGY_REFERENCE =" not in rendering_text
    assert "TAGGING_TERMINOLOGY_REFERENCE =" in helpers_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in rendering_text
        assert f"def {name}" in helpers_text


def test_rendering_reexports_next_step_helpers() -> None:
    """Next-step helpers stay importable from rendering after the split."""
    rendering = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering")
    helpers = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering_next_steps")

    for name in MOVED_HELPER_NAMES:
        assert getattr(rendering, name) is getattr(helpers, name)
    assert rendering.TAGGING_TERMINOLOGY_REFERENCE is helpers.TAGGING_TERMINOLOGY_REFERENCE
    assert callable(rendering.build_status_result)
    assert callable(rendering.emit_status_result)
    assert callable(rendering.render_status)
