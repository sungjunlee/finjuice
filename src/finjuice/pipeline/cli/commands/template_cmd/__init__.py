"""Template command stable entrypoint and thin Typer wrapper."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import typer

from finjuice.pipeline.analytics.duckdb_layer import (
    DUCKDB_INSTALL_HINT,
    DuckDBAnalytics,
    validate_readonly_sql,
)
from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.audit_log import append_audit_event
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.cli.report_filters import (
    count_matched_report_filters,
    load_cli_report_filters,
)

from .execution import (
    TemplateExecutionDependencies,
    TemplateRunEvent,
    execute_template_run,
    write_template_run_event,
)
from .options import (
    ListOptions,
    RawTemplateRunOptions,
    ShowOptions,
    TemplateRunOptions,
    error_exit_code,
    resolve_run_options,
)
from .registry import (
    TemplateUnknownError,
    load_template_list,
    load_template_show,
)
from .rendering import (
    emit_template_list,
    emit_template_show,
    render_template_run_result,
)
from .result import TemplateRunAuditState

logger = logging.getLogger(__name__)

template_app = typer.Typer(
    name="template",
    help="Run curated SQL query templates, including dynamic pivot tables",
    no_args_is_help=True,
)


def _dependencies() -> TemplateExecutionDependencies:
    """Build dependencies from package globals for testability."""
    return TemplateExecutionDependencies(
        duckdb_analytics=DuckDBAnalytics,
        validate_readonly_sql=validate_readonly_sql,
        load_cli_report_filters=load_cli_report_filters,
        count_matched_report_filters=count_matched_report_filters,
    )


def _log_template_run_event(
    *,
    data_dir: Path,
    template_name: str,
    success: bool,
    output_format: str,
    json_output: bool = False,
    user_params: dict[str, str],
    duration: float,
    row_count: Optional[int] = None,
    error_type: Optional[str] = None,
) -> None:
    """Record template run result for metrics extraction."""
    write_template_run_event(
        TemplateRunEvent(
            data_dir=data_dir,
            template_name=template_name,
            success=success,
            output_format=output_format,
            json_output=json_output,
            user_params=user_params,
            duration=duration,
            row_count=row_count,
            error_type=error_type,
        ),
        append_event=append_audit_event,
        warn=cli_output.warning,
    )


def _log_template_failure(
    options: TemplateRunOptions,
    audit_state: TemplateRunAuditState,
    *,
    error_type: str,
) -> None:
    """Write an audit event for a failed template run."""
    _log_template_run_event(
        data_dir=options.config.data_dir,
        template_name=options.name,
        success=False,
        output_format=options.output_format,
        json_output=options.machine_output,
        user_params=audit_state.user_params,
        duration=time.perf_counter() - audit_state.started_at,
        error_type=error_type,
    )


@template_app.command("list")
def list_templates(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List available query templates."""
    options = ListOptions(json_output=json_output)
    try:
        result = load_template_list(options)
    except Exception as e:  # intended catch-all for CLI robustness
        cli_output.emit_error(
            f"Failed to load template registry: {e}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="template list",
        )
        raise  # defensive: emit_error is NoReturn, but guard against future regressions

    emit_template_list(result, json_output=options.json_output)


@template_app.command("show")
def show_template(
    name: str = typer.Argument(..., help="Template name"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show template metadata and SQL definition."""
    options = ShowOptions(name=name, json_output=json_output)
    try:
        result = load_template_show(options)
    except TemplateUnknownError as e:
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="template show",
        )
        raise  # defensive: emit_error is NoReturn
    except typer.Exit:
        raise
    except Exception as e:  # intended catch-all for CLI robustness
        cli_output.emit_error(
            f"Failed to show template: {e}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="template show",
        )
        raise  # defensive: emit_error is NoReturn

    emit_template_show(result, json_output=options.json_output)


@template_app.command("run")
def run_template(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Template name"),
    param: list[str] = typer.Option(
        [],
        "--param",
        "-p",
        help="Template parameter in key=value format. Repeat for multiple parameters.",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: table, csv, json, markdown, xlsx",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        help="Save output to file. Required when --output xlsx.",
    ),
    limit: int = typer.Option(
        cli_output.DEFAULT_PAGINATION_LIMIT,
        "--limit",
        help="Maximum rows to return (max 10000)",
    ),
    cursor: str = typer.Option("0", "--cursor", help="Opaque pagination cursor"),
    max_bytes: int = typer.Option(
        cli_output.DEFAULT_MAX_BYTES,
        "--max-bytes",
        help="Maximum serialized JSON response size before truncating rows",
    ),
) -> None:
    """Run a SQL template with validated parameters."""
    options = resolve_run_options(
        RawTemplateRunOptions(
            ctx=ctx,
            name=name,
            param=param,
            output=output,
            json_output=json_output,
            file=file,
            limit=limit,
            cursor=cursor,
            max_bytes=max_bytes,
        )
    )
    audit_state = TemplateRunAuditState(started_at=time.perf_counter())

    try:
        result = execute_template_run(
            options,
            dependencies=_dependencies(),
            audit_state=audit_state,
        )
        row_count = render_template_run_result(result)
        _log_template_run_event(
            data_dir=options.config.data_dir,
            template_name=options.name,
            success=True,
            output_format=options.output_format,
            json_output=options.machine_output,
            user_params=result.user_params,
            duration=time.perf_counter() - audit_state.started_at,
            row_count=row_count,
        )
    except TemplateUnknownError as e:
        _log_template_failure(options, audit_state, error_type="TyperExit")
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=error_exit_code(options.machine_output, ExitCode.USAGE_ERROR),
            json_output=options.machine_output,
            command="template run",
        )
    except typer.Exit:
        _log_template_failure(options, audit_state, error_type="TyperExit")
        raise
    except ImportError as e:
        if str(e) != DUCKDB_INSTALL_HINT:
            raise
        _log_template_failure(options, audit_state, error_type=type(e).__name__)
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.QUERY_ERROR,
            suggestion="finjuice doctor",
            json_output=options.machine_output,
            command="template run",
        )
    except ValueError as e:
        _log_template_failure(options, audit_state, error_type=type(e).__name__)
        cli_output.emit_error(
            str(e),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=error_exit_code(options.machine_output, ExitCode.VALIDATION_ERROR),
            json_output=options.machine_output,
            command="template run",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        _log_template_failure(options, audit_state, error_type=type(e).__name__)
        logger.error(f"Template execution failed: {e}", exc_info=True)
        cli_output.emit_error(
            f"Template execution failed: {e}",
            error_code=ErrorCode.QUERY_ERROR,
            json_output=options.machine_output,
            command="template run",
        )
