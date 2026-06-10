"""Internal contract tests for template command layers."""

from pathlib import Path

import typer
from click import Command

from finjuice.pipeline.cli.commands.template_cmd.options import (
    ListOptions,
    ShowOptions,
    TemplateRunOptions,
)
from finjuice.pipeline.cli.commands.template_cmd.result import TemplateRunResult
from finjuice.pipeline.config import Config


def test_template_command_options_are_typed_boundaries(tmp_path: Path) -> None:
    """Template command wrappers should hand typed options to execution layers."""
    ctx = typer.Context(Command("template-run"))
    config = Config(tmp_path)

    list_options = ListOptions(json_output=True)
    show_options = ShowOptions(name="monthly_spend", json_output=False)
    run_options = TemplateRunOptions(
        ctx=ctx,
        config=config,
        name="monthly_spend",
        params=("since=2024-01",),
        output_format="json",
        json_output=True,
        file=None,
        limit=100,
        cursor_offset=0,
        max_bytes=10_000,
    )

    assert list_options.json_output is True
    assert show_options.name == "monthly_spend"
    assert run_options.machine_output is True


def test_template_run_result_keeps_rendering_payload_separate() -> None:
    """Execution should return a structured result instead of printing directly."""
    result = TemplateRunResult(
        template_name="monthly_spend",
        result_df=None,
        row_count=0,
        total_row_count=0,
        pagination={"next_cursor": None},
        output_format="json",
        file=None,
        machine_output=True,
        filters_applied=0,
        template_meta_extras={},
        pivot_columns=None,
        user_params={},
        max_bytes=10_000,
        duration=0.0,
    )

    assert result.template_name == "monthly_spend"
    assert result.pivot_columns is None
