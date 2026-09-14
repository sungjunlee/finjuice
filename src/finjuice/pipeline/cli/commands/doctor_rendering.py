"""Human-readable Rich rendering for ``finjuice doctor``.

Owns check-result formatting and the human report layout. The Typer command,
CLI capability probe, and JSON payload stay in
:mod:`finjuice.pipeline.cli.commands.doctor`.
"""

from __future__ import annotations

from rich.markup import escape
from rich.panel import Panel

from finjuice.pipeline.cli.output import console
from finjuice.pipeline.doctor import CheckResult, DoctorResult


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

    if result.metadata:
        revision = result.metadata.get("dataset_revision")
        generation = result.metadata.get("dataset_generation")
        if revision is not None and generation is not None:
            console.print(f"Repository revision {revision} ({generation})", markup=False)
        else:
            console.print("Canonical data unavailable", markup=False)
        console.print("환경 및 대기 파일 상태는 별도 관측 결과입니다.")
        console.print()

    for title, checks in result.sections:
        console.print(f"[bold cyan]{title}:[/bold cyan]")
        for check in checks:
            _print_check_result(check)
        console.print()

    console.print(f"[bold green]💡 다음 단계:[/bold green] [cyan]{escape(result.next_step)}[/cyan]")
    console.print()


def _print_check_result(result: CheckResult) -> None:
    """Print a check result with proper formatting."""
    # Main message
    if result.status == "ok":
        console.print(f"  {result.icon} {escape(result.message)}")
    elif result.status == "warning":
        console.print(f"  {result.icon} [yellow]{escape(result.message)}[/yellow]")
    else:
        console.print(f"  {result.icon} [red]{escape(result.message)}[/red]")

    # Detail (indented)
    if result.detail:
        console.print(f"     [dim]{escape(result.detail)}[/dim]")

    # Suggestion (indented with arrow)
    if result.suggestion:
        console.print(f"     → [green]{escape(result.suggestion)}[/green]")
