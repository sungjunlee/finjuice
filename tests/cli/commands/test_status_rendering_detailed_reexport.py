"""Identity checks for the status rendering detailed-snapshot helper split."""

from __future__ import annotations

import importlib
from pathlib import Path

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")

MOVED_HELPER_NAMES = (
    "_render_detailed_stats",
    "_render_detailed_amounts",
    "_render_structural_sources",
    "_render_top_categories",
    "_format_currency",
)


def test_detailed_snapshot_helpers_live_in_helper_module() -> None:
    """Detailed snapshot helpers should not live in rendering.py."""
    rendering_text = (STATUS_DIR / "rendering.py").read_text(encoding="utf-8")
    helpers_text = (STATUS_DIR / "rendering_detailed.py").read_text(encoding="utf-8")

    assert "def build_status_result" in rendering_text
    assert "def emit_status_result" in rendering_text
    assert "def render_status" in rendering_text
    assert "def _render_status_footnotes" in rendering_text
    assert "def _render_next_steps" in rendering_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in rendering_text
        assert f"def {name}" in helpers_text


def test_rendering_reexports_detailed_snapshot_helpers() -> None:
    """Detailed snapshot helpers stay importable from rendering after the split."""
    rendering = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering")
    helpers = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering_detailed")

    for name in MOVED_HELPER_NAMES:
        assert getattr(rendering, name) is getattr(helpers, name)
    assert callable(rendering.build_status_result)
    assert callable(rendering.emit_status_result)
    assert callable(rendering.render_status)
    assert callable(rendering._render_status_footnotes)
    assert callable(rendering._render_next_steps)
