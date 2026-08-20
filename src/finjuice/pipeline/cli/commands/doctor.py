"""Doctor command: thin Typer wrapper around pipeline doctor checks."""

from __future__ import annotations

import inspect

import typer
from rich.panel import Panel

from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor import CheckResult, DoctorResult, _build_doctor_result
from finjuice.pipeline.doctor import checks as doctor_checks


def _probe_cli_capabilities() -> dict[str, bool]:
    """Inspect CLI command signatures without leaking that import into core."""
    try:
        from finjuice.pipeline.cli.commands.tag import tag_command

        return {"tag.edit": "edit" in inspect.signature(tag_command).parameters}
    except (ImportError, AttributeError):
        return {"tag.edit": False}


def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Diagnose environment and identify issues.

    Performs comprehensive checks on:
    - System (Python version, finjuice version, OS)
    - Data directory (existence, permissions, structure)
    - Configuration (rules.yaml, environment variables)
    - Data (transactions, imports, processing status)
    - Dependencies (required and optional packages)
    """
    config: Config = ctx.obj["config"]
    doctor_checks._probe_cli_capabilities = _probe_cli_capabilities
    result = _build_doctor_result(config)
    emit(
        result.payload,
        json_output,
        lambda _: _render_doctor_result(result),
        command="doctor",
    )


def _render_doctor_result(result: DoctorResult) -> None:
    """Render the human-readable doctor report."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]🔍 finjuice 환경 진단[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    for title, checks in result.sections:
        console.print(f"[bold cyan]{title}:[/bold cyan]")
        for check in checks:
            _print_check_result(check)
        console.print()

    console.print(f"[bold green]💡 다음 단계:[/bold green] [cyan]{result.next_step}[/cyan]")
    console.print()


def _print_check_result(result: CheckResult) -> None:
    """Print a check result with proper formatting."""
    # Main message
    if result.status == "ok":
        console.print(f"  {result.icon} {result.message}")
    elif result.status == "warning":
        console.print(f"  {result.icon} [yellow]{result.message}[/yellow]")
    else:
        console.print(f"  {result.icon} [red]{result.message}[/red]")

    # Detail (indented)
    if result.detail:
        console.print(f"     [dim]{result.detail}[/dim]")

    # Suggestion (indented with arrow)
    if result.suggestion:
        console.print(f"     → [green]{result.suggestion}[/green]")


def register_doctor_command(app: typer.Typer) -> None:
    """Register the doctor command with the main app."""
    app.command(name="doctor", rich_help_panel="Admin")(doctor)
