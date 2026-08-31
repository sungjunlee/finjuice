"""
CLI output helper module for standardized terminal output.

Provides consistent formatting, colors, and icons across all CLI commands.
Replaces scattered typer.echo calls with semantic output functions.

Pagination and JSON ``_meta`` envelope helpers live in
:mod:`finjuice.pipeline.cli.output_pagination` and are re-exported here.
Rich semantic message helpers live in
:mod:`finjuice.pipeline.cli.output_messages` and are re-exported here.
"""

import json
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Any, Callable, Mapping, NoReturn, Optional

import typer
from rich.console import Console

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


# ---------------------------------------------------------------------------
# Structured error codes (Issue #282)
# ---------------------------------------------------------------------------
class ErrorCode(str, Enum):
    """Machine-readable error codes for agent consumption."""

    GENERAL_ERROR = "GENERAL_ERROR"
    DATA_DIR_NOT_INITIALIZED = "DATA_DIR_NOT_INITIALIZED"
    NO_DATA = "NO_DATA"
    RULES_FILE_NOT_FOUND = "RULES_FILE_NOT_FOUND"
    RULE_NOT_FOUND = "RULE_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_ACCESS_ERROR = "FILE_ACCESS_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_ARGS = "INVALID_ARGS"
    TAGGING_FAILED = "TAGGING_FAILED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    QUERY_ERROR = "QUERY_ERROR"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    USER_CANCELLED = "USER_CANCELLED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"

    def __str__(self) -> str:
        """Return the wire value for string-formatting compatibility."""
        return self.value

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return accepted JSON error-code values in declaration order."""
        return tuple(code.value for code in cls)


# ---------------------------------------------------------------------------
# Semantic exit codes (Issue #286, follows gh CLI pattern)
# ---------------------------------------------------------------------------
class ExitCode(IntEnum):
    """Semantic exit codes for agent error-type distinction."""

    SUCCESS = 0
    OK = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    VALIDATION_ERROR = 3
    NO_DATA = 4
    USER_CANCELLED = 130

    def __str__(self) -> str:
        """Return the integer wire value for string-formatting compatibility."""
        return str(int(self))

    @classmethod
    def items(cls, *, include_aliases: bool = True) -> tuple[tuple[str, int], ...]:
        """Return public exit-code names and integer values."""
        if include_aliases:
            return tuple((name, int(code)) for name, code in cls.__members__.items())
        return tuple((code.name, int(code)) for code in cls)

    @classmethod
    def values(cls) -> tuple[int, ...]:
        """Return unique accepted process exit integers in declaration order."""
        return tuple(int(code) for code in cls)


ERROR_CODE_CATALOG: Mapping[str, ErrorCode] = MappingProxyType(
    {code.value: code for code in ErrorCode}
)
EXIT_CODE_CATALOG: Mapping[str, ExitCode] = MappingProxyType(dict(ExitCode.__members__))


def error_code_values() -> tuple[str, ...]:
    """Return accepted JSON error-code values in declaration order."""
    return ErrorCode.values()


def exit_code_items(*, include_aliases: bool = True) -> tuple[tuple[str, int], ...]:
    """Return public exit-code names and values for manifest/schema discovery."""
    return ExitCode.items(include_aliases=include_aliases)


def exit_code_values() -> tuple[int, ...]:
    """Return unique accepted process exit integers in declaration order."""
    return ExitCode.values()


def _normalize_error_code(error_code: ErrorCode | str) -> str:
    """Return the JSON wire value for a typed or legacy string error code."""
    if isinstance(error_code, ErrorCode):
        return error_code.value
    return str(error_code)


def _normalize_exit_code(exit_code: ExitCode | int) -> int:
    """Return the process integer value for a typed or legacy integer exit code."""
    return int(exit_code)


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
