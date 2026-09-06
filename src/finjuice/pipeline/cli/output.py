"""
CLI output helper module for standardized terminal output.

Provides consistent formatting, colors, and icons across all CLI commands.
Replaces scattered typer.echo calls with semantic output functions.

Pagination and JSON ``_meta`` envelope helpers live in
:mod:`finjuice.pipeline.cli.output_pagination` and are re-exported here.
Rich semantic message helpers live in
:mod:`finjuice.pipeline.cli.output_messages` and are re-exported here.
Structured error/exit code catalogs live in
:mod:`finjuice.pipeline.cli.output_codes` and are re-exported here.
"""

import json
from typing import Any, Callable, NoReturn, Optional

import typer
from rich.console import Console

from finjuice.pipeline.cli.output_codes import (
    ERROR_CODE_CATALOG,  # noqa: F401 — re-exported for existing output imports
    EXIT_CODE_CATALOG,  # noqa: F401 — re-exported for existing output imports
    ErrorCode,
    ExitCode,
    _normalize_error_code,
    _normalize_exit_code,
    error_code_values,  # noqa: F401 — re-exported for existing output imports
    exit_code_items,  # noqa: F401 — re-exported for existing output imports
    exit_code_values,  # noqa: F401 — re-exported for existing output imports
)
from finjuice.pipeline.cli.output_messages import (  # noqa: F401
    bullet_list,
    error,
    error_with_ai_hint,
    hr,
    info,
    newline,
    panel_info,
    progress_indicator,
    section,
    step,
    success,
    table_summary,
    warning,
)
from finjuice.pipeline.cli.output_pagination import (  # noqa: F401
    DEFAULT_MAX_BYTES,
    DEFAULT_PAGINATION_LIMIT,
    MAX_PAGINATION_LIMIT,
    Pagination,
    _build_meta,
    build_offset_pagination,
    render_pagination_footer,
    truncate_rows_to_max_bytes,
    validate_pagination_args,
    wrap_paginated_result,
)

# Global console instance (can be overridden for testing)
console = Console(stderr=True)


def emit(
    result: dict[str, Any],
    json_output: bool,
    render_fn: Callable[[dict[str, Any]], None],
    *,
    command: str = "",
    meta_extras: Optional[dict[str, Any]] = None,
) -> None:
    """Emit structured CLI output as JSON or Rich text.

    When *json_output* is True, a ``_meta`` envelope is injected into *result*
    before serialisation (Issue #284).  The envelope carries schema_version,
    finjuice_version, command name, and an ISO-8601 timestamp.
    """
    if json_output:
        if command and isinstance(result, dict):
            result = {"_meta": _build_meta(command, extras=meta_extras), **result}
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        render_fn(result)


def emit_list(
    items: list[Any],
    json_output: bool,
    render_fn: Callable[[list[Any]], None],
    *,
    command: str,
    items_key: str = "items",
    extras: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a list-type CLI result with a JSON envelope."""
    if json_output:
        payload: dict[str, Any] = {
            "_meta": _build_meta(command),
            items_key: items,
            "count": len(items),
        }
        if extras:
            payload.update(extras)
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        render_fn(items)


def emit_error(
    message: str,
    *,
    error_code: ErrorCode | str = ErrorCode.GENERAL_ERROR,
    exit_code: ExitCode | int = ExitCode.GENERAL_ERROR,
    suggestion: str | None = None,
    json_output: bool = False,
    command: str = "",
    meta_extras: Optional[dict[str, Any]] = None,
    privacy: Any | None = None,
) -> NoReturn:
    """Emit a structured error response and exit.

    Args:
        message: Human-readable error description.
        error_code: Machine-readable error code from ErrorCode.
        exit_code: Process exit code from ExitCode.
        suggestion: Optional remediation command or hint.
        json_output: When True, emit JSON to stdout instead of Rich text.
        command: Optional command name for injecting a ``_meta`` envelope.
        meta_extras: Optional additive metadata for the JSON ``_meta`` envelope.
        privacy: Optional privacy profile for selected JSON command errors.
    """
    error_code_value = _normalize_error_code(error_code)
    exit_code_value = _normalize_exit_code(exit_code)

    if json_output:
        meta_payload = dict(meta_extras or {})
        if privacy is not None:
            from finjuice.pipeline.cli.privacy import (
                is_lower_pii_profile,
                privacy_meta,
                redact_error_message,
            )

            meta_payload.update(privacy_meta(privacy))
            if is_lower_pii_profile(privacy):
                message = redact_error_message(message)
                if suggestion is not None:
                    suggestion = redact_error_message(suggestion)

        error_obj: dict[str, Any] = {
            "code": error_code_value,
            "message": message,
            "suggestion": suggestion,
        }
        payload: dict[str, Any] = {
            "_meta": _build_meta(command or "unknown", extras=meta_payload),
            "error": error_obj,
            "exit_code": exit_code_value,
        }
        typer.echo(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        console.print(f"[red]❌ {message}[/red]")
    raise typer.Exit(code=exit_code_value)


def _render_markdown_cell(value: Any) -> str:
    """Render one Markdown table cell with minimal escaping."""
    if value is None:
        text = ""
    else:
        text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\n", "<br>")
    return text


def render_markdown_table(headers: list[str], rows: list[tuple[Any, ...] | list[Any]]) -> str:
    """Render GitHub-flavored Markdown table text."""
    if not headers:
        return ""

    normalized_headers = [_render_markdown_cell(header) for header in headers]
    separator = ["---"] * len(normalized_headers)
    lines = [
        f"| {' | '.join(normalized_headers)} |",
        f"| {' | '.join(separator)} |",
    ]

    column_count = len(normalized_headers)
    for row in rows:
        row_values = list(row)
        normalized_row = [
            _render_markdown_cell(row_values[index] if index < len(row_values) else "")
            for index in range(column_count)
        ]
        lines.append(f"| {' | '.join(normalized_row)} |")

    return "\n".join(lines)


def render_markdown_dataframe(dataframe: Any) -> str:
    """Render a DataFrame-like object without pandas/tabulate dependency."""
    headers = [str(column) for column in getattr(dataframe, "columns", [])]
    rows = list(dataframe.rows())
    return render_markdown_table(headers, rows)
