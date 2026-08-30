"""Identity tests for the status rendering helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands.status import rendering, rendering_helpers

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")


def test_status_table_helpers_live_in_helper_module() -> None:
    """Main status table construction should not live in the rendering module."""
    rendering_text = (STATUS_DIR / "rendering.py").read_text(encoding="utf-8")
    helpers_text = (STATUS_DIR / "rendering_helpers.py").read_text(encoding="utf-8")

    assert "def build_status_result" in rendering_text
    assert "def emit_status_result" in rendering_text
    assert "def render_status" in rendering_text
    assert "class StatusResult" in rendering_text
    assert "def _add_data_rows" not in rendering_text
    assert "def _add_schema_row" not in rendering_text
    assert "def _add_tagging_rate_row" not in rendering_text
    assert "def _tagging_rate_style" not in rendering_text
    assert "def _build_status_table" not in rendering_text
    assert "def _add_data_rows" in helpers_text
    assert "def _add_schema_row" in helpers_text
    assert "def _add_tagging_rate_row" in helpers_text
    assert "def _tagging_rate_style" in helpers_text
    assert "def _build_status_table" in helpers_text


def test_status_table_helpers_reexport_from_rendering() -> None:
    """Existing rendering imports should keep resolving to the table helpers."""
    rendering_text = (STATUS_DIR / "rendering.py").read_text(encoding="utf-8")

    assert "class StatusRenderContext" in rendering_text
    assert "class StatusResult" in rendering_text
    assert "def build_status_result" in rendering_text
    assert "def emit_status_result" in rendering_text
    assert "def render_status" in rendering_text
    assert "_build_status_table" in rendering_text
    assert "_add_data_rows" in rendering_text
    assert "_tagging_rate_style" in rendering_text
    assert rendering._build_status_table is rendering_helpers._build_status_table
    assert rendering._add_data_rows is rendering_helpers._add_data_rows
    assert rendering._add_schema_row is rendering_helpers._add_schema_row
    assert rendering._add_import_row is rendering_helpers._add_import_row
    assert rendering._add_tagging_rate_row is rendering_helpers._add_tagging_rate_row
    assert rendering._tagging_rate_style is rendering_helpers._tagging_rate_style
    assert rendering._add_transfer_rows is rendering_helpers._add_transfer_rows
    assert rendering._add_untagged_rows is rendering_helpers._add_untagged_rows
    assert rendering._add_rules_row is rendering_helpers._add_rules_row
    assert callable(rendering.build_status_result)
    assert callable(rendering.emit_status_result)
    assert callable(rendering.render_status)
