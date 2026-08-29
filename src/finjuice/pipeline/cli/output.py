"""
CLI output helper module for standardized terminal output.

Provides consistent formatting, colors, and icons across all CLI commands.
Replaces scattered typer.echo calls with semantic output functions.

Pagination and JSON ``_meta`` envelope helpers live in
:mod:`finjuice.pipeline.cli.output_pagination` and are re-exported here.
"""

import json
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Any, Callable, Mapping, NoReturn, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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


def success(message: str, prefix: str = "✅") -> None:
    """Print success message in green with checkmark icon.

    Args:
        message: Success message to display
        prefix: Icon prefix (default: ✅)

    Example:
        >>> success("Validation complete!")
        ✅ Validation complete!
    """
    console.print(f"[green]{prefix} {message}[/green]")


def info(message: str, prefix: str = "ℹ️") -> None:
    """Print informational message in blue.

    Args:
        message: Info message to display
        prefix: Icon prefix (default: ℹ️)

    Example:
        >>> info("Processing 150 transactions...")
        ℹ️  Processing 150 transactions...
    """
    console.print(f"[blue]{prefix}  {message}[/blue]")


def warning(message: str, prefix: str = "⚠️") -> None:
    """Print warning message in yellow.

    Args:
        message: Warning message to display
        prefix: Icon prefix (default: ⚠️)

    Example:
        >>> warning("No rules matched this transaction")
        ⚠️  No rules matched this transaction
    """
    console.print(f"[yellow]{prefix}  {message}[/yellow]")


def error(message: str, prefix: str = "❌") -> None:
    """Print error message in red.

    Args:
        message: Error message to display
        prefix: Icon prefix (default: ❌)

    Example:
        >>> error("Failed to load rules.yaml")
        ❌ Failed to load rules.yaml
    """
    console.print(f"[red]{prefix} {message}[/red]")


def error_with_ai_hint(message: str, ai_prompt: str, prefix: str = "❌") -> None:
    """Print error message with AI troubleshooting hint.

    Args:
        message: Error message to display
        ai_prompt: Suggested prompt for Claude/ChatGPT
        prefix: Icon prefix (default: ❌)

    Example:
        >>> error_with_ai_hint(
        ...     "No XLSX files found",
        ...     "뱅크샐러드에서 파일을 어떻게 내보내고 어디에 넣어야 하지?"
        ... )
        ❌ No XLSX files found

        💡 AI에게 물어보기:
        ┌─ Claude/ChatGPT 프롬프트 ─┐
        │ 뱅크샐러드에서 파일을...    │
        └─────────────────────────────┘
    """
    console.print(f"[red]{prefix} {message}[/red]")
    console.print()
    console.print("[dim]💡 AI에게 물어보기:[/dim]")
    console.print(
        Panel(
            ai_prompt.strip(),
            title="Claude/ChatGPT 프롬프트",
            border_style="blue",
            padding=(0, 1),
        )
    )


def step(number: int, message: str) -> None:
    """Print numbered step message.

    Args:
        number: Step number
        message: Step description

    Example:
        >>> step(1, "Validating rules...")
        [1/3] Validating rules...
    """
    console.print(f"[cyan][{number}][/cyan] {message}")


def section(title: str) -> None:
    """Print section header with separator.

    Args:
        title: Section title

    Example:
        >>> section("Validation Results")

        ════════════════════════════════════════
        Validation Results
        ════════════════════════════════════════
    """
    console.print()
    console.rule(f"[bold]{title}[/bold]")
    console.print()


def panel_info(content: str, title: Optional[str] = None, border_style: str = "blue") -> None:
    """Print content in a bordered panel.

    Args:
        content: Panel content (can be multi-line)
        title: Optional panel title
        border_style: Rich color name for border (default: blue)

    Example:
        >>> panel_info("Next steps:\\n1. Edit rules.yaml\\n2. Run finjuice tag", title="Next Steps")
        ╭─ Next Steps ─────────────────────╮
        │ Next steps:                      │
        │ 1. Edit rules.yaml               │
        │ 2. Run finjuice tag               │
        ╰──────────────────────────────────╯
    """
    console.print(Panel(content, title=title, border_style=border_style))


def table_summary(
    title: str,
    rows: list[tuple[str, str]],
    columns: tuple[str, str] = ("Item", "Value"),
) -> None:
    """Print summary table with key-value pairs.

    Args:
        title: Table title
        rows: List of (key, value) tuples
        columns: Column headers (default: ("Item", "Value"))

    Example:
        >>> table_summary(
        ...     "Validation Summary",
        ...     [("Total Rules", "15"), ("Passed", "12"), ("Warnings", "3")]
        ... )
        ┏━━━━━━━━━━━━━┳━━━━━━━┓
        ┃ Item        ┃ Value ┃
        ┡━━━━━━━━━━━━━╇━━━━━━━┩
        │ Total Rules │ 15    │
        │ Passed      │ 12    │
        │ Warnings    │ 3     │
        └─────────────┴───────┘
    """
    table = Table(title=title, show_header=True)
    table.add_column(columns[0], style="cyan")
    table.add_column(columns[1], style="green")

    for key, value in rows:
        table.add_row(key, value)

    console.print(table)


def bullet_list(items: list[str], style: str = "dim") -> None:
    """Print bulleted list.

    Args:
        items: List of items to display
        style: Rich style for bullets (default: dim)

    Example:
        >>> bullet_list(["Item 1", "Item 2", "Item 3"])
        • Item 1
        • Item 2
        • Item 3
    """
    for item in items:
        console.print(f"[{style}]•[/{style}] {item}")


def progress_indicator(current: int, total: int, description: str = "") -> None:
    """Print progress indicator (simple percentage).

    Args:
        current: Current progress value
        total: Total value
        description: Optional description

    Example:
        >>> progress_indicator(7, 10, "Processing files")
        [70%] Processing files (7/10)
    """
    percentage = int((current / total) * 100) if total > 0 else 0
    progress_text = f"[{percentage}%]"

    if description:
        progress_text += f" {description}"

    progress_text += f" ({current}/{total})"
    console.print(f"[cyan]{progress_text}[/cyan]")


def newline() -> None:
    """Print a blank line for spacing."""
    console.print()


def hr() -> None:
    """Print horizontal rule separator."""
    console.rule(style="dim")


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
