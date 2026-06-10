"""Typed CLI option contracts for template commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

SUPPORTED_OUTPUTS = {"table", "csv", "json", "markdown", "xlsx"}


@dataclass(frozen=True)
class ListOptions:
    """Normalized options for `finjuice template list`."""

    json_output: bool


@dataclass(frozen=True)
class ShowOptions:
    """Normalized options for `finjuice template show`."""

    name: str
    json_output: bool


@dataclass(frozen=True)
class TemplateRunOptions:
    """Normalized options for `finjuice template run`."""

    ctx: typer.Context
    config: Config
    name: str
    params: tuple[str, ...]
    output_format: str
    json_output: bool
    file: Path | None
    limit: int
    cursor_offset: int
    max_bytes: int

    @property
    def machine_output(self) -> bool:
        """Return whether the run is emitting machine-readable JSON."""
        return self.output_format == "json"


@dataclass(frozen=True)
class RawTemplateRunOptions:
    """Raw Typer arguments before validation and pagination coercion."""

    ctx: typer.Context
    name: str
    param: list[str]
    output: str | None
    json_output: bool
    file: Path | None
    limit: int
    cursor: str
    max_bytes: int


def error_exit_code(json_mode: bool, structured: ExitCode) -> ExitCode:
    """Return the legacy exit code for text vs JSON error modes."""
    return structured if json_mode else ExitCode.GENERAL_ERROR


def resolve_run_options(raw_options: RawTemplateRunOptions) -> TemplateRunOptions:
    """Validate public CLI flags and return typed run options."""
    requested_output = (
        raw_options.output.lower().strip() if raw_options.output is not None else None
    )
    if raw_options.json_output:
        if requested_output is None:
            output_format = "json"
        elif requested_output != "json":
            cli_output.emit_error(
                "Cannot use --json with a conflicting --output value. Use --output json or --json.",
                error_code=ErrorCode.INVALID_ARGS,
                exit_code=ExitCode.USAGE_ERROR,
                json_output=True,
                command="template run",
            )
        else:
            output_format = "json"
    else:
        output_format = requested_output or "table"

    if output_format not in SUPPORTED_OUTPUTS:
        cli_output.emit_error(
            f"Unsupported output format: {output_format}. "
            f"Supported: {', '.join(sorted(SUPPORTED_OUTPUTS))}",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=error_exit_code(output_format == "json", ExitCode.USAGE_ERROR),
            json_output=output_format == "json",
            command="template run",
        )

    if output_format == "xlsx" and raw_options.file is None:
        cli_output.emit_error(
            "--file is required when --output xlsx",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=False,
            command="template run",
        )

    resolved_limit, cursor_offset, resolved_max_bytes = cli_output.validate_pagination_args(
        raw_options.limit,
        raw_options.cursor,
        raw_options.max_bytes,
        json_output=output_format == "json",
        command="template run",
    )

    return TemplateRunOptions(
        ctx=raw_options.ctx,
        config=get_config(raw_options.ctx),
        name=raw_options.name,
        params=tuple(raw_options.param),
        output_format=output_format,
        json_output=raw_options.json_output,
        file=raw_options.file,
        limit=resolved_limit,
        cursor_offset=cursor_offset,
        max_bytes=resolved_max_bytes,
    )
