"""Rich semantic message helpers for CLI output.

These helpers print success/info/warning/error text, section chrome, and
simple tables. Public names stay importable from
:mod:`finjuice.pipeline.cli.output`.
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _console() -> Console:
    """Return the live CLI console so tests can rebind ``output.console``."""
    from finjuice.pipeline.cli.output import console

    return console


def success(message: str, prefix: str = "✅") -> None:
    """Print success message in green with checkmark icon.

    Args:
        message: Success message to display
        prefix: Icon prefix (default: ✅)

    Example:
        >>> success("Validation complete!")
        ✅ Validation complete!
    """
    _console().print(f"[green]{prefix} {message}[/green]")


def info(message: str, prefix: str = "ℹ️") -> None:
    """Print informational message in blue.

    Args:
        message: Info message to display
        prefix: Icon prefix (default: ℹ️)

    Example:
        >>> info("Processing 150 transactions...")
        ℹ️  Processing 150 transactions...
    """
    _console().print(f"[blue]{prefix}  {message}[/blue]")


def warning(message: str, prefix: str = "⚠️") -> None:
    """Print warning message in yellow.

    Args:
        message: Warning message to display
        prefix: Icon prefix (default: ⚠️)

    Example:
        >>> warning("No rules matched this transaction")
        ⚠️  No rules matched this transaction
    """
    _console().print(f"[yellow]{prefix}  {message}[/yellow]")


def error(message: str, prefix: str = "❌") -> None:
    """Print error message in red.

    Args:
        message: Error message to display
        prefix: Icon prefix (default: ❌)

    Example:
        >>> error("Failed to load rules.yaml")
        ❌ Failed to load rules.yaml
    """
    _console().print(f"[red]{prefix} {message}[/red]")


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
    console = _console()
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
    _console().print(f"[cyan][{number}][/cyan] {message}")


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
    console = _console()
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
    _console().print(Panel(content, title=title, border_style=border_style))


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

    _console().print(table)


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
    console = _console()
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
    _console().print(f"[cyan]{progress_text}[/cyan]")


def newline() -> None:
    """Print a blank line for spacing."""
    _console().print()


def hr() -> None:
    """Print horizontal rule separator."""
    _console().rule(style="dim")
