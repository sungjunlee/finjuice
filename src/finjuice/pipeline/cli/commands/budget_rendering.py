"""Human-readable Rich rendering for ``finjuice budget``.

Owns KRW/progress formatting, unmatched-goal warnings, and the
status/edit/validate tables. Typer commands and JSON payloads stay in
:mod:`finjuice.pipeline.cli.commands.budget`, which re-exports the names
used by existing callers.
"""

from __future__ import annotations

from typing import Any

from rich.table import Table

from finjuice.pipeline.cli.output import console

BUDGET_SPEND_INCLUSION = (
    "spend excludes savings/transfers/investments matching the shared non-consumption pattern"
)


def _render_budget_status(result: dict[str, Any]) -> None:
    """Render budget status in Rich tables."""
    console.print(f"\n[bold cyan]📒 Budget Status[/bold cyan] [dim]{result['month']}[/dim]\n")
    console.print(f"[dim]{BUDGET_SPEND_INCLUSION}[/dim]\n")

    goals_file = result["goals_file"]
    if not goals_file["exists"]:
        console.print(f"[yellow]⚠️  No goals.yaml found at {goals_file['path']}[/yellow]")
        console.print("[dim]Start from templates/goals.yaml.example or use budget edit.[/dim]\n")
        return

    summary = result["summary"]
    assert summary is not None

    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Field", style="bold cyan")
    summary_table.add_column("Value")
    summary_table.add_row("Goals file", goals_file["path"])
    if goals_file.get("updated"):
        summary_table.add_row("Updated", goals_file["updated"])
    if goals_file.get("notes"):
        summary_table.add_row("Notes", goals_file["notes"])
    summary_table.add_row("Total target", _format_currency(summary["target"]))
    summary_table.add_row("Total actual", _format_currency(summary["actual"]))
    summary_table.add_row("Remaining", _format_currency(summary["remaining"]))
    summary_table.add_row(
        "Progress",
        _format_progress(summary["progress_pct"], summary["status"]),
    )
    console.print(summary_table)
    console.print()

    category_table = Table(title="Categories")
    category_table.add_column("Category", style="bold")
    category_table.add_column("Target", justify="right")
    category_table.add_column("Actual", justify="right")
    category_table.add_column("Remaining", justify="right")
    category_table.add_column("Progress", justify="right")
    category_table.add_column("Status", justify="center")

    for row in result["categories"]:
        category_table.add_row(
            str(row["name"]),
            _format_currency(int(row["target"])),
            _format_currency(int(row["actual"])),
            _format_currency(int(row["remaining"])),
            _format_progress(row["progress_pct"], row["status"]),
            _style_status(str(row["status"])),
        )

    if not result["categories"]:
        category_table.add_row("[dim]No categories configured[/dim]", "-", "-", "-", "-", "-")

    console.print(category_table)
    _render_unmatched_goal_warning(result.get("unmatched_goal_categories") or [])
    filters_applied = result.get("_filters_applied", 0)
    if filters_applied > 0:
        console.print(
            f"\n[dim]active filters: {filters_applied} "
            "(use --no-filter to compare full results)[/dim]"
        )
    console.print()


def _render_budget_edit(result: dict[str, Any]) -> None:
    """Render budget-edit confirmation text."""
    console.print(f"[green]✅ Updated {result['path']}[/green]")
    for change in result["changes"]:
        console.print(
            f"  [cyan]{change['path']}[/cyan]: "
            f"{_display_change_value(change['old'])} -> {_display_change_value(change['new'])}"
        )
    console.print()


def _render_budget_validate(result: dict[str, Any]) -> None:
    """Render goals.yaml validation results."""
    if not result["_has_errors"]:
        console.print(f"[green]✅ goals.yaml is valid[/green]\n[dim]{result['path']}[/dim]")
        return

    console.print(f"[red]❌ goals.yaml validation failed[/red]\n[dim]{result['path']}[/dim]")
    for index, problem in enumerate(result["_problems"], start=1):
        console.print(f"  {index}. {problem.format()}")


def _format_currency(amount: int) -> str:
    """Format a KRW integer with separators."""
    return f"₩{amount:,}"


def _style_status(status: str) -> str:
    """Return a colored Rich token for the status enum."""
    if status == "over":
        return "[red]over[/red]"
    if status == "on-track":
        return "[green]on-track[/green]"
    return "[cyan]under[/cyan]"


def _format_progress(progress_pct: float | None, status: str) -> str:
    """Render progress_pct with status-aware styling."""
    if progress_pct is None:
        if status == "over":
            return "[red]-[/red]"
        return "-"
    rendered = f"{progress_pct:.2f}%"
    if status == "over":
        return f"[red]{rendered}[/red]"
    if status == "on-track":
        return f"[green]{rendered}[/green]"
    return f"[cyan]{rendered}[/cyan]"


def _display_change_value(value: Any) -> str:
    """Render old/new values for edit confirmations."""
    if value is None:
        return "∅"
    if isinstance(value, int):
        return _format_currency(value)
    return str(value)


def _render_unmatched_goal_warning(unmatched: list[dict[str, Any]]) -> None:
    """Render a warning for goal names that did not bind to spend categories."""
    if not unmatched:
        return

    names = ", ".join(str(item["name"]) for item in unmatched)
    examples: list[str] = []
    for item in unmatched:
        for suggested in item.get("suggested") or []:
            if suggested not in examples:
                examples.append(suggested)
    example_text = f" (e.g. {', '.join(examples)})" if examples else ""
    console.print(
        "\n[yellow]⚠️  Goals categories not matching any spend category: "
        f"{names} — goals.yaml names must exactly match category_final values"
        f"{example_text}; use `finjuice budget edit --set` or fix goals.yaml.[/yellow]"
    )
