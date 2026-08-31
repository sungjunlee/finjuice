"""Identity checks for the status rendering table-row helper split."""

from __future__ import annotations

import importlib


def test_rendering_reexports_table_row_helpers() -> None:
    """Table-row helpers stay importable from rendering after the split."""
    rendering = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering")
    helpers = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering_table")

    assert rendering._build_status_table is helpers._build_status_table
    assert rendering._add_data_rows is helpers._add_data_rows
    assert rendering._add_schema_row is helpers._add_schema_row
    assert rendering._add_import_row is helpers._add_import_row
    assert rendering._add_tagging_rate_row is helpers._add_tagging_rate_row
    assert rendering._tagging_rate_style is helpers._tagging_rate_style
    assert rendering._add_transfer_rows is helpers._add_transfer_rows
    assert rendering._add_untagged_rows is helpers._add_untagged_rows
    assert rendering._add_rules_row is helpers._add_rules_row


def test_rendering_keeps_public_status_api() -> None:
    """Public status rendering names stay on rendering after the split."""
    rendering = importlib.import_module("finjuice.pipeline.cli.commands.status.rendering")

    assert rendering.__all__ == [
        "StatusRenderContext",
        "StatusResult",
        "build_status_result",
        "emit_status_result",
        "render_status",
    ]
    assert callable(rendering.build_status_result)
    assert callable(rendering.emit_status_result)
    assert callable(rendering.render_status)
