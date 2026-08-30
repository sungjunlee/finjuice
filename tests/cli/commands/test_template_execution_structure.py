"""Identity tests for the template execution helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands.template_cmd import execution, execution_helpers

TEMPLATE_CMD_DIR = Path("src/finjuice/pipeline/cli/commands/template_cmd")

MOVED_HELPER_NAMES = (
    "PIVOT_COL_AXIS_EXPRESSIONS",
    "PIVOT_OTHER_BUCKET",
    "PIVOT_ROW_AXIS_EXPRESSIONS",
    "PivotAgg",
    "PivotValue",
    "_build_pivot_base_rows_sql",
    "_build_pivot_bucket_case",
    "_build_pivot_column_projection",
    "_build_pivot_months_where",
    "_build_pivot_rank_expr",
    "_discover_pivot_columns",
    "_next_month_start",
    "_normalize_pivot_agg",
    "_quote_sql_identifier",
)


def test_pivot_sql_helpers_live_in_helper_module() -> None:
    """Pivot SQL builders should not live in the execution orchestration module."""
    execution_text = (TEMPLATE_CMD_DIR / "execution.py").read_text(encoding="utf-8")
    helpers_text = (TEMPLATE_CMD_DIR / "execution_helpers.py").read_text(encoding="utf-8")

    assert "def execute_template_run" in execution_text
    assert "def _run_pivot_template" in execution_text
    assert "def write_template_run_event" in execution_text
    assert "def _render_sql" in execution_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in execution_text
        assert name in helpers_text
    assert "def _quote_sql_identifier" in helpers_text
    assert "def _next_month_start" in helpers_text
    assert "def _build_pivot_months_where" in helpers_text
    assert "def _normalize_pivot_agg" in helpers_text
    assert "def _build_pivot_base_rows_sql" in helpers_text
    assert "def _build_pivot_rank_expr" in helpers_text
    assert "def _discover_pivot_columns" in helpers_text
    assert "def _build_pivot_bucket_case" in helpers_text
    assert "def _build_pivot_column_projection" in helpers_text


def test_pivot_sql_helpers_reexport_from_execution() -> None:
    """Existing execution imports should keep resolving to the pivot SQL builders."""
    execution_text = (TEMPLATE_CMD_DIR / "execution.py").read_text(encoding="utf-8")

    assert "def _run_pivot_template" in execution_text
    for name in MOVED_HELPER_NAMES:
        assert name in execution_text
        assert getattr(execution, name) is getattr(execution_helpers, name)
    assert callable(execution.execute_template_run)
    assert callable(execution.write_template_run_event)
    assert callable(execution._render_sql)
