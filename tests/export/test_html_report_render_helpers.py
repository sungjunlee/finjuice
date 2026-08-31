"""Template asset helpers stay re-exported from html_report_render after the split."""

from __future__ import annotations

import importlib


def test_html_report_render_reexports_template_helpers() -> None:
    """Plotly.js tag and Jinja2 template helpers stay importable after the split."""
    render = importlib.import_module("finjuice.pipeline.export.html_report_render")
    helpers = importlib.import_module("finjuice.pipeline.export.html_report_render_helpers")

    assert render.__all__ == [
        "_get_template_content",
        "_plotly_js_tag",
        "_format_currency",
        "_render_html_report",
        "_render_table_rows",
    ]
    assert render._plotly_js_tag is helpers._plotly_js_tag
    assert render._get_template_content is helpers._get_template_content
    assert callable(render._render_html_report)
    assert callable(render._render_table_rows)
    assert callable(render._format_currency)
