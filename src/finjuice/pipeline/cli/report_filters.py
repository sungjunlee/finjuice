"""Shared CLI helpers for report_filters and the root --no-filter flag.

The side-effect-free filter-application helpers (`apply_report_filters`,
`count_matched_report_filters`) live in the core `finjuice.pipeline.report_filters`
module. They are re-exported here so CLI command modules keep a single
report-filter import surface.
"""

from __future__ import annotations

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.config import Config
from finjuice.pipeline.report_filters import apply_report_filters, count_matched_report_filters
from finjuice.pipeline.tagging.rules import ReportFilters, load_report_filters

__all__ = [
    "apply_report_filters",
    "count_matched_report_filters",
    "load_cli_report_filters",
    "no_filter_requested",
]


def no_filter_requested(ctx: typer.Context) -> bool:
    """Return True when the root CLI callback disabled report_filters."""
    root_obj = ctx.find_root().obj if ctx is not None else None
    return bool(((root_obj or ctx.obj) or {}).get("no_filter", False))


def load_cli_report_filters(
    ctx: typer.Context,
    config: Config,
    *,
    command: str,
    json_output: bool,
) -> ReportFilters:
    """Load report filters for a CLI command, honoring the root --no-filter flag."""
    if no_filter_requested(ctx):
        return ReportFilters()

    try:
        return load_report_filters(config.rules_file)
    except ValueError as exc:
        emit_error(
            f"Failed to load report filters: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
