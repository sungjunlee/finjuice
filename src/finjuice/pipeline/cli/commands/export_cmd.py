"""Export command for finjuice CLI."""

import logging
from typing import Any, Optional

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.export_helpers import (
    render_export_dry_run,
    validate_format,
    validate_period,
)
from finjuice.pipeline.cli.export_runtime import configure_cli_export_result_runtime
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, _build_meta, emit, emit_error
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.export import result as export_result

logger = logging.getLogger(__name__)


def _render_export_result(result: dict[str, Any]) -> None:
    """Render human-readable export result."""
    output.success("[OK] Export complete:")
    tx = result.get("transaction_count", 0)
    if tx:
        output.info(f"  Transactions: {tx}")
    for item in result.get("output_files", []):
        output.info(f"  → {item['path']}")


def export_command(
    ctx: typer.Context,
    format: str = typer.Option(
        "xlsx",
        "--format",
        "-f",
        help="Export format: xlsx, html, md, all",
    ),
    period: Optional[str] = typer.Option(
        None,
        "--period",
        "-p",
        help="Period filter (YYYY-MM format, e.g., 2024-10)",
    ),
    auto_open: bool = typer.Option(
        True,
        "--auto-open/--no-auto-open",
        help="Auto-open report in browser/viewer (HTML only)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Preview output files without writing",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    online: bool = typer.Option(
        False,
        "--online",
        help="Load Plotly.js from CDN (default: offline/embedded for privacy)",
    ),
) -> dict[str, Any]:
    """
    Generate master XLSX, HTML, and/or Markdown reports.

    Exports:
    - xlsx: master_YYYYMMDD.xlsx + CSV reports (default). The master workbook
      stays unfiltered for auditability; report CSVs honor report_filters unless
      the root --no-filter flag is set.
    - html: Interactive HTML report with Plotly charts. Honors report_filters by default.
    - md: GitHub-friendly Markdown report. Honors report_filters by default.
    - all: All formats (xlsx + html + md)

    Examples:
        # Default XLSX export
        finjuice export

        # HTML report with charts (auto-opens in browser)
        finjuice export --format html

        # Markdown for version control
        finjuice export --format md

        # October 2024 only
        finjuice export --format html --period 2024-10

        # All formats
        finjuice export --format all

        # Disable auto-open
        finjuice export --format html --no-auto-open
    """
    config = get_config(ctx)
    configure_cli_export_result_runtime()

    # Validate inputs
    format_lower = validate_format(format, json_output)
    validate_period(period, json_output)

    try:
        result = export_result._compute_export_result(
            ctx,
            config,
            format_lower,
            period,
            auto_open,
            dry_run,
            emit_text=not json_output,
            online=online,
        )
        json_result = result
        if json_output:
            json_result = {k: v for k, v in result.items() if not k.startswith("_")}
            json_result["_meta"] = {
                **_build_meta("export"),
                "filters_applied": result.get("_filters_applied", 0),
            }
        emit(
            json_result,
            json_output,
            render_export_dry_run if dry_run else _render_export_result,
            command="export",
        )
        return result

    except typer.Exit:
        raise  # Re-raise typer.Exit without modification
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Export failed (%s)", type(e).__name__)
        emit_error(
            f"File access error: {e}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="export",
        )
    except (ValueError, RuntimeError) as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        emit_error(
            f"Export failed: {e}",
            error_code=ErrorCode.EXPORT_FAILED,
            json_output=json_output,
            command="export",
        )
    except KeyboardInterrupt:
        emit_error(
            "Export cancelled by user.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command="export",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Unexpected error during export: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="export",
        )
