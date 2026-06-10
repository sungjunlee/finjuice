"""CLI wiring for core export result computation."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.report_filters import load_cli_report_filters
from finjuice.pipeline.cli.utils import open_file_in_system_viewer
from finjuice.pipeline.export.result import configure_export_result_runtime
from finjuice.pipeline.tagging.models import ReportFilters


def _load_export_report_filters(ctx: Any, config: Any, json_output: bool) -> ReportFilters:
    """Load export report filters with the CLI error contract."""
    return load_cli_report_filters(
        ctx,
        config,
        command="export",
        json_output=json_output,
    )


def configure_cli_export_result_runtime() -> None:
    """Connect CLI output, file opening, and filter errors to core export computation."""
    configure_export_result_runtime(
        info=output.info,
        warning=output.warning,
        open_file=open_file_in_system_viewer,
        report_filters_loader=_load_export_report_filters,
    )
