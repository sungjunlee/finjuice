"""Helper functions for the export command.

Extracted from export_cmd.py to keep each module ≤300 lines (Issue #269).
"""

import re
from typing import Any

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.export import result as export_result

# Helpers live in the core export module (Issue #745). These shim re-exports
# preserve the public symbols formerly defined here so existing callers keep
# working without depending on cli.commands.* internals.
_REPORT_OUTPUTS = export_result._REPORT_OUTPUTS
format_size_bytes = export_result.format_size_bytes
estimate_output_size_bytes = export_result.estimate_output_size_bytes
build_output_entry = export_result.build_output_entry
build_export_plan = export_result.build_export_plan


def render_export_dry_run(plan: dict[str, Any]) -> None:
    """Render the human-readable export dry-run preview."""
    output.info("[Dry-run Summary]")
    output.info(f"  Transactions available: {plan['transaction_count']}")

    if plan["output_files"]:
        output.info("  Would generate:")
        for item in plan["output_files"]:
            size_hint = item["estimated_size_human"] or "size estimate unavailable"
            output.info(f"    → {item['path']} ({size_hint})")

    for item in plan["skipped_outputs"]:
        output.warning(f"  Skipped: {item['path']} ({item['reason']})")

    output.warning("⚠️  No files written (dry-run mode)")


def validate_format(format_str: str, json_output: bool) -> str:
    """Validate export format option. Returns lowercase format or exits."""
    valid_formats = {"xlsx", "html", "md", "all"}
    if format_str.lower() not in valid_formats:
        emit_error(
            f"Invalid format: {format_str}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="export",
        )
    return format_str.lower()


def validate_period(
    period: str | None,
    json_output: bool,
    *,
    command: str = "export",
    privacy: Any | None = None,
) -> None:
    """Validate period format (YYYY-MM) or exit."""
    if not period:
        return
    match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{2})$", period)
    if not match:
        emit_error(
            f"Invalid period format: {period}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command,
            privacy=privacy,
        )
    month = int(match.group("month"))
    if not (1 <= month <= 12):
        emit_error(
            f"Invalid month in period: {period}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command,
            privacy=privacy,
        )
