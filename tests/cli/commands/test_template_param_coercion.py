"""Identity tests for the template param_coercion helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands.template_cmd import (
    param_coercion,
    param_coercion_helpers,
)

TEMPLATE_CMD_DIR = Path("src/finjuice/pipeline/cli/commands/template_cmd")


def test_month_window_helpers_live_in_helper_module() -> None:
    """YYYY-MM window parsing should not live in the coercion module."""
    coercion_text = (TEMPLATE_CMD_DIR / "param_coercion.py").read_text(encoding="utf-8")
    helpers_text = (TEMPLATE_CMD_DIR / "param_coercion_helpers.py").read_text(encoding="utf-8")

    assert "def _coerce_param_value" in coercion_text
    assert "def _resolve_param_values" in coercion_text
    assert "def _resolve_sql_params" in coercion_text
    assert "def _resolve_template_context" in coercion_text
    assert "def _parse_month_start" not in coercion_text
    assert "def _expand_month_range" not in coercion_text
    assert "def _parse_month_window" not in coercion_text
    assert "def _parse_month_start" in helpers_text
    assert "def _expand_month_range" in helpers_text
    assert "def _parse_month_window" in helpers_text


def test_month_window_helpers_reexport_from_param_coercion() -> None:
    """Existing param_coercion imports should keep resolving to the month helpers."""
    assert param_coercion.MONTH_PATTERN is param_coercion_helpers.MONTH_PATTERN
    assert param_coercion.MONTH_WINDOW_FORMAT is param_coercion_helpers.MONTH_WINDOW_FORMAT
    assert param_coercion._parse_month_start is param_coercion_helpers._parse_month_start
    assert param_coercion._expand_month_range is param_coercion_helpers._expand_month_range
    assert param_coercion._parse_month_window is param_coercion_helpers._parse_month_window
    assert callable(param_coercion._coerce_param_value)
    assert callable(param_coercion._resolve_sql_params)
    assert callable(param_coercion._resolve_template_context)
