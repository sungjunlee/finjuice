"""Budget commands backed by goals.yaml."""

from __future__ import annotations

import json
from typing import Any, NoReturn

import typer
from rich.table import Table

from finjuice.pipeline.budget_compute import (
    BUDGET_EDIT_UPDATE_HINT,
    BudgetEditCancelledError,
    GoalsFileInvalidError,
    compute_budget_edit,
    compute_budget_status,
    compute_budget_validate,
)
from finjuice.pipeline.cli.commands.budget_period import resolve_budget_period
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, _build_meta, console, emit_error
from finjuice.pipeline.cli.report_filters import load_cli_report_filters
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.goals import GoalsValidationProblem

BUDGET_SPEND_INCLUSION = (
    "spend excludes savings/transfers/investments matching the shared non-consumption pattern"
)

budget_app = typer.Typer(
    name="budget",
    help="Track declarative monthly budgets from goals.yaml",
    no_args_is_help=True,
)


@budget_app.command("status")
def budget_status_command(
    ctx: typer.Context,
    month: str | None = typer.Option(None, "--month", help="Budget month (YYYY-MM)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show monthly budget targets vs actual consumption spend.

    Spend excludes savings/transfers/investments matching the shared
    non-consumption pattern used by monthly_consumption_summary.
    """
    config = get_config(ctx)
    try:
        resolved_month = resolve_budget_period(month, csv_base_dir=config.csv_base_dir)
        result = compute_budget_status(
            config,
            month=resolved_month,
            load_report_filters=lambda: load_cli_report_filters(
                ctx,
                config,
                command="budget status",
                json_output=json_output,
            ),
        )
    except GoalsFileInvalidError as exc:
        _raise_goals_validation_error(
            command="budget status",
            problems=exc.problems,
            json_output=json_output,
        )
    except ValueError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget status",
        )
    if json_output:
        meta = _build_meta(
            "budget status",
            extras={
                "filters_applied": result["_filters_applied"],
                "month": result["month"],
                "inclusion": BUDGET_SPEND_INCLUSION,
            },
        )
        payload = {k: v for k, v in result.items() if not k.startswith("_")}
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
        return

    _render_budget_status(result)


@budget_app.command("edit")
def budget_edit_command(
    ctx: typer.Context,
    updates: list[str] = typer.Option(
        [],
        "--set",
        metavar="KEY=VALUE",
        help=("Update one field in goals.yaml. " + BUDGET_EDIT_UPDATE_HINT),
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Edit monthly budget values in goals.yaml while preserving comments."""
    if not updates:
        emit_error(
            "At least one --set KEY=VALUE update is required",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget edit",
        )

    config = get_config(ctx)
    try:
        result = compute_budget_edit(
            config,
            updates=updates,
            confirm=(
                None
                if yes
                else lambda count: typer.confirm(
                    f"Write {count} change(s) to {config.goals_file}?",
                    default=False,
                )
            ),
        )
    except GoalsFileInvalidError as exc:
        _raise_goals_validation_error(
            command="budget edit",
            problems=exc.problems,
            json_output=json_output,
        )
    except BudgetEditCancelledError:
        raise typer.Exit(code=ExitCode.USER_CANCELLED) from None
    except ValueError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget edit",
        )
    if json_output:
        meta = _build_meta("budget edit")
        payload = {k: v for k, v in result.items() if not k.startswith("_")}
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
        return

    _render_budget_edit(result)


@budget_app.command("validate")
def budget_validate_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate goals.yaml against the monthly_budget schema."""
    config = get_config(ctx)
    result = compute_budget_validate(config)
    payload = {k: v for k, v in result.items() if not k.startswith("_")}

    if json_output:
        meta = _build_meta("budget validate")
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
    else:
        _render_budget_validate(result)

    if result["_has_errors"]:
        raise typer.Exit(ExitCode.VALIDATION_ERROR)


def _raise_goals_validation_error(
    *,
    command: str,
    problems: list[GoalsValidationProblem],
    json_output: bool,
) -> NoReturn:
    """Raise a structured validation error for goals.yaml issues."""
    message = "goals.yaml is invalid"
    if problems:
        message = message + ":\n" + "\n".join(problem.format() for problem in problems)
    emit_error(
        message,
        error_code=ErrorCode.VALIDATION_FAILED,
        exit_code=ExitCode.VALIDATION_ERROR,
        json_output=json_output,
        command=command,
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
