"""Budget commands backed by goals.yaml."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import typer
from rich.table import Table
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, _build_meta, console, emit_error
from finjuice.pipeline.cli.report_filters import apply_report_filters, load_cli_report_filters
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_transfers_for
from finjuice.pipeline.goals import (
    GoalsValidationProblem,
    MonthlyBudget,
    load_goals_file,
    load_goals_roundtrip,
    new_goals_document,
    validate_goals_payload,
    validate_month_literal,
    write_goals_roundtrip,
)
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA, get_partition_path

logger = logging.getLogger(__name__)

STATUS_ON_TRACK_MIN_PCT = 90.0
_BUDGET_EDIT_UPDATE_HINT = (
    "Use total=..., categories.<name>=..., monthly_budget.categories.<name>=..., "
    "or bare category names such as 식비=700000."
)
_RESERVED_BUDGET_EDIT_KEYS = {
    "categories",
    "monthly_budget",
    "monthly_budget.categories",
    "updated",
    "monthly_budget.updated",
    "notes",
    "monthly_budget.notes",
    "version",
}

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
    """Show monthly budget targets vs actual spending."""
    config = get_config(ctx)
    try:
        result = _compute_budget_status(config, ctx, month=month, json_output=json_output)
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
        help=("Update one field in goals.yaml. " + _BUDGET_EDIT_UPDATE_HINT),
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
        result = _compute_budget_edit(
            config,
            updates=updates,
            assume_yes=yes,
            json_output=json_output,
        )
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
    result = _compute_budget_validate(config)
    payload = {k: v for k, v in result.items() if not k.startswith("_")}

    if json_output:
        meta = _build_meta("budget validate")
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
    else:
        _render_budget_validate(result)

    if result["_has_errors"]:
        raise typer.Exit(ExitCode.VALIDATION_ERROR)


def _compute_budget_status(
    config: Config,
    ctx: typer.Context,
    *,
    month: str | None,
    json_output: bool,
) -> dict[str, Any]:
    """Compute the budget status payload."""
    resolved_month = _resolve_budget_month(config, month)
    goals_result = load_goals_file(config.goals_file)
    goals_file = {
        "path": str(config.goals_file),
        "exists": goals_result.exists,
    }

    if not goals_result.exists:
        _, filters_applied = _load_budget_actuals(
            config,
            ctx,
            month=resolved_month,
            json_output=json_output,
        )
        return {
            "month": resolved_month,
            "goals_file": goals_file,
            "summary": None,
            "categories": [],
            **_build_budget_guidance(
                month=resolved_month,
                goals_exists=False,
                summary=None,
                category_rows=[],
                filters_applied=filters_applied,
            ),
            "_filters_applied": filters_applied,
        }

    if goals_result.document is None:
        _raise_goals_validation_error(
            command="budget status",
            problems=goals_result.problems,
            json_output=json_output,
        )

    assert goals_result.document is not None
    budget = goals_result.document.monthly_budget
    actuals, filters_applied = _load_budget_actuals(
        config,
        ctx,
        month=resolved_month,
        json_output=json_output,
    )

    category_rows = _build_category_rows(budget, actuals)
    summary = _build_summary_row(budget, actuals)
    goals_file["updated"] = budget.updated
    goals_file["notes"] = budget.notes

    return {
        "month": resolved_month,
        "goals_file": goals_file,
        "summary": summary,
        "categories": category_rows,
        **_build_budget_guidance(
            month=resolved_month,
            goals_exists=True,
            summary=summary,
            category_rows=category_rows,
            filters_applied=filters_applied,
        ),
        "_filters_applied": filters_applied,
    }


def _compute_budget_edit(
    config: Config,
    *,
    updates: list[str],
    assume_yes: bool,
    json_output: bool,
) -> dict[str, Any]:
    """Apply round-trip goals.yaml edits after validation."""
    try:
        yaml, loaded = load_goals_roundtrip(config.goals_file)
    except (OSError, YAMLError) as exc:
        _raise_goals_validation_error(
            command="budget edit",
            problems=[_parse_problem_from_exception(exc)],
            json_output=json_output,
        )
        raise AssertionError("unreachable")

    if loaded is None:
        document = new_goals_document()
    elif not isinstance(loaded, CommentedMap):
        _raise_goals_validation_error(
            command="budget edit",
            problems=[
                GoalsValidationProblem(
                    path="goals.yaml",
                    message="must contain a mapping",
                )
            ],
            json_output=json_output,
        )
        raise AssertionError("unreachable")
    else:
        document = loaded

    _bootstrap_budget_document(document)

    changes = [_apply_budget_update(document, item) for item in updates]
    validated_document, problems = validate_goals_payload(document)
    if validated_document is None:
        _raise_goals_validation_error(
            command="budget edit",
            problems=problems,
            json_output=json_output,
        )
    assert validated_document is not None

    if not assume_yes:
        confirmed = typer.confirm(
            f"Write {len(changes)} change(s) to {config.goals_file}?",
            default=False,
        )
        if not confirmed:
            raise typer.Exit(code=ExitCode.USER_CANCELLED)

    write_goals_roundtrip(yaml, document, config.goals_file)
    result = {
        "path": str(config.goals_file),
        "changes": changes,
        "monthly_budget": _serialize_monthly_budget(validated_document.monthly_budget),
    }
    return result


def _compute_budget_validate(config: Config) -> dict[str, Any]:
    """Validate goals.yaml and build a renderable payload."""
    result = load_goals_file(config.goals_file)
    if not result.exists:
        problems = [
            GoalsValidationProblem(
                path=str(config.goals_file),
                message="file not found",
            )
        ]
        return {
            "status": "invalid",
            "path": str(config.goals_file),
            "problems": [_serialize_problem(problem) for problem in problems],
            "_problems": problems,
            "_has_errors": True,
        }

    problems = result.problems
    return {
        "status": "valid" if not problems else "invalid",
        "path": str(config.goals_file),
        "problems": [_serialize_problem(problem) for problem in problems],
        "_problems": problems,
        "_has_errors": bool(problems),
    }


def _render_budget_status(result: dict[str, Any]) -> None:
    """Render budget status in Rich tables."""
    console.print(f"\n[bold cyan]📒 Budget Status[/bold cyan] [dim]{result['month']}[/dim]\n")

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


def _resolve_budget_month(config: Config, requested_month: str | None) -> str:
    """Resolve the effective budget month."""
    if requested_month is not None:
        return validate_month_literal(requested_month, param_name="month")

    latest_month = _latest_partition_month(config.csv_base_dir)
    if latest_month is not None:
        return latest_month
    return datetime.now().astimezone().strftime("%Y-%m")


def _latest_partition_month(csv_base_dir: Path) -> str | None:
    """Return the latest YYYY-MM partition containing transactions.csv."""
    if not csv_base_dir.exists():
        return None

    months = [
        f"{path.parent.parent.name}-{path.parent.name}"
        for path in csv_base_dir.glob("*/*/transactions.csv")
        if path.is_file()
    ]
    if not months:
        return None
    return sorted(months)[-1]


def _load_budget_actuals(
    config: Config,
    ctx: typer.Context,
    *,
    month: str,
    json_output: bool,
) -> tuple[dict[str, int], int]:
    """Load one month's filtered expense actuals by category."""
    year, month_value = month.split("-", 1)
    partition_path = get_partition_path(config.csv_base_dir, int(year), int(month_value))
    if not partition_path.exists():
        return {}, 0

    try:
        source_df = pl.read_csv(
            partition_path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
        )
    except (FileNotFoundError, pl.exceptions.PolarsError, OSError) as exc:
        logger.warning("Could not read budget partition %s: %s", partition_path, exc)
        return {}, 0

    report_filters = load_cli_report_filters(
        ctx,
        config,
        command="budget status",
        json_output=json_output,
    )
    filtered_df, filters_applied = apply_report_filters(source_df, report_filters)
    expense_df = _expense_rows(filtered_df)
    if expense_df.is_empty():
        return {}, filters_applied

    grouped = (
        expense_df.with_columns(_budget_category_expr(expense_df).alias("budget_category"))
        .group_by("budget_category")
        .agg(pl.col("amount").abs().sum().alias("actual_amount"))
        .sort("actual_amount", descending=True)
    )
    actuals = {str(row[0]): int(round(float(row[1]))) for row in grouped.iter_rows()}
    return actuals, filters_applied


def _expense_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Return expense rows with transfers excluded."""
    if df.is_empty() or "amount" not in df.columns:
        return df.head(0)

    expr = pl.col("amount") < 0
    if "type_norm" in df.columns:
        expr = expr & (pl.col("type_norm").cast(pl.Utf8, strict=False) == "expense")
    expr = expr & exclude_transfers_for(df)
    return df.filter(expr)


def _budget_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build the category fallback chain used for budget rollups."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8, strict=False))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])


def _build_category_rows(
    monthly_budget: MonthlyBudget,
    actuals: dict[str, int],
) -> list[dict[str, Any]]:
    """Build per-category rows from configured budgets plus unbudgeted spend."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, target in monthly_budget.categories.items():
        actual = actuals.get(name, 0)
        rows.append(_status_row(name, target, actual))
        seen.add(name)

    unbudgeted = [
        (name, actual) for name, actual in actuals.items() if name not in seen and actual > 0
    ]
    for name, actual in sorted(unbudgeted, key=lambda item: (-item[1], item[0])):
        rows.append(_status_row(name, 0, actual))

    return rows


def _build_summary_row(monthly_budget: MonthlyBudget, actuals: dict[str, int]) -> dict[str, Any]:
    """Build the overall budget summary row."""
    total_actual = sum(actuals.values())
    return _status_row("Total", monthly_budget.total, total_actual)


def _status_row(name: str, target: int, actual: int) -> dict[str, Any]:
    """Build one budget status row."""
    remaining = target - actual
    progress_pct = round((actual / target) * 100, 2) if target > 0 else None
    status = _budget_status(progress_pct=progress_pct, target=target, actual=actual)
    return {
        "name": name,
        "target": target,
        "actual": actual,
        "remaining": remaining,
        "progress_pct": progress_pct,
        "status": status,
    }


def _build_budget_guidance(
    *,
    month: str,
    goals_exists: bool,
    summary: dict[str, Any] | None,
    category_rows: list[dict[str, Any]],
    filters_applied: int,
) -> dict[str, Any]:
    """Build additive health/action cues for budget status."""
    over_budget_count = sum(
        1 for row in category_rows if row["status"] == "over" and row["target"] > 0
    )
    unbudgeted_count = sum(1 for row in category_rows if row["target"] == 0 and row["actual"] > 0)
    on_track_count = sum(1 for row in category_rows if row["status"] == "on-track")
    under_budget_count = sum(1 for row in category_rows if row["status"] == "under")
    over_budget_categories = [
        row["name"] for row in category_rows if row["status"] == "over" and row["target"] > 0
    ]
    unbudgeted_categories = [
        row["name"] for row in category_rows if row["target"] == 0 and row["actual"] > 0
    ]
    at_risk_categories = [
        row["name"]
        for row in category_rows
        if row["status"] in {"on-track", "over"} or (row["target"] == 0 and row["actual"] > 0)
    ]

    reasons: list[str] = []
    if not goals_exists:
        reasons.append("missing_goals_file")
    else:
        if over_budget_count > 0:
            reasons.append("over_budget_categories")
        if unbudgeted_count > 0:
            reasons.append("unbudgeted_spend")

    next_steps: list[dict[str, str]] = []
    if not goals_exists:
        next_steps.append(
            {
                "signal": "missing_goals_file",
                "message": "Create monthly budget targets before relying on budget status.",
                "command": "finjuice budget edit --help",
            }
        )
    elif reasons:
        if "over_budget_categories" in reasons or "unbudgeted_spend" in reasons:
            review_signal = (
                "over_budget_categories"
                if "over_budget_categories" in reasons
                else "unbudgeted_spend"
            )
            next_steps.append(
                {
                    "signal": review_signal,
                    "message": "Inspect this month's review queue before changing the budget.",
                    "command": f"finjuice review --json --month {month}",
                }
            )
        next_steps.append(
            {
                "signal": "budget_adjustment",
                "message": "Update goals.yaml targets when the current budget is outdated.",
                "command": "finjuice budget edit --help",
            }
        )

    return {
        "health": {
            "status": "critical" if not goals_exists else "warning" if reasons else "ok",
            "reasons": reasons,
        },
        "actionable": bool(reasons),
        "signals": {
            "goals_file_exists": goals_exists,
            "over_budget_count": over_budget_count,
            "unbudgeted_count": unbudgeted_count,
            "on_track_count": on_track_count,
            "under_budget_count": under_budget_count,
            "remaining_total": None if summary is None else summary["remaining"],
            "filters_applied": filters_applied,
        },
        "review": {
            "month": month,
            "target": None if summary is None else summary["target"],
            "actual": None if summary is None else summary["actual"],
            "remaining": None if summary is None else summary["remaining"],
            "at_risk_categories": at_risk_categories,
            "over_budget_categories": over_budget_categories,
            "unbudgeted_categories": unbudgeted_categories,
        },
        "next_steps": next_steps,
    }


def _budget_status(*, progress_pct: float | None, target: int, actual: int) -> str:
    """Return the status enum for one budget row."""
    if target <= 0:
        return "over" if actual > 0 else "on-track"
    if progress_pct is None:
        return "under"
    if progress_pct > 100.0:
        return "over"
    if progress_pct >= STATUS_ON_TRACK_MIN_PCT:
        return "on-track"
    return "under"


def _apply_budget_update(document: CommentedMap, raw_update: str) -> dict[str, Any]:
    """Apply one --set KEY=VALUE edit to the round-trip YAML document."""
    if "=" not in raw_update:
        raise ValueError(f"Invalid --set format: {raw_update} (expected key=value)")
    raw_key, raw_value = raw_update.split("=", 1)
    key = raw_key.strip()
    if not key:
        raise ValueError(f"Invalid --set format: {raw_update} (empty key)")

    monthly_budget = _ensure_mapping(document, "monthly_budget")
    categories = _ensure_mapping(monthly_budget, "categories")

    if key == "total" or key == "monthly_budget.total":
        old_value = monthly_budget.get("total")
        monthly_budget["total"] = _parse_budget_int(raw_value, key="monthly_budget.total")
        return {"path": "monthly_budget.total", "old": old_value, "new": monthly_budget["total"]}

    if key in _RESERVED_BUDGET_EDIT_KEYS:
        raise ValueError(f"Invalid budget key: {key}. {_BUDGET_EDIT_UPDATE_HINT}")

    category_name = key
    if key.startswith("monthly_budget."):
        if not key.startswith("monthly_budget.categories."):
            raise ValueError(f"Invalid budget key: {key}. {_BUDGET_EDIT_UPDATE_HINT}")
        category_name = key.removeprefix("monthly_budget.categories.")
    elif key.startswith("categories."):
        category_name = key.removeprefix("categories.")
    category_name = category_name.strip()
    if not category_name:
        raise ValueError(f"Invalid budget key: {key}. {_BUDGET_EDIT_UPDATE_HINT}")

    old_value = categories.get(category_name)
    categories[category_name] = _parse_budget_int(
        raw_value,
        key=f"monthly_budget.categories.{category_name}",
    )
    return {
        "path": f"monthly_budget.categories.{category_name}",
        "old": old_value,
        "new": categories[category_name],
    }


def _ensure_mapping(parent: CommentedMap, key: str) -> CommentedMap:
    """Ensure a nested mapping exists inside a round-trip YAML document."""
    current = parent.get(key)
    if current is None:
        current = CommentedMap()
        parent[key] = current
    if not isinstance(current, CommentedMap):
        if isinstance(current, dict):
            current = CommentedMap(current)
            parent[key] = current
        else:
            raise ValueError(f"{key} must be a mapping before it can be edited")
    return current


def _bootstrap_budget_document(document: CommentedMap) -> None:
    """Ensure the minimum monthly_budget skeleton exists for edits."""
    if "version" not in document:
        document.insert(0, "version", 1)

    monthly_budget = _ensure_mapping(document, "monthly_budget")
    if "total" not in monthly_budget:
        monthly_budget.insert(0, "total", 0)
    _ensure_mapping(monthly_budget, "categories")


def _parse_budget_int(raw_value: str, *, key: str) -> int:
    """Parse a non-negative integer budget value."""
    stripped = raw_value.strip()
    try:
        value = int(stripped)
    except ValueError as exc:
        raise ValueError(f"{key} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _serialize_monthly_budget(monthly_budget: MonthlyBudget) -> dict[str, Any]:
    """Serialize the validated monthly budget payload."""
    return {
        "total": monthly_budget.total,
        "categories": dict(monthly_budget.categories),
        "updated": monthly_budget.updated,
        "notes": monthly_budget.notes,
    }


def _serialize_problem(problem: GoalsValidationProblem) -> dict[str, Any]:
    """Serialize a validation problem for JSON output."""
    return {
        "path": problem.path,
        "message": problem.message,
        "line": problem.line,
        "column": problem.column,
        "formatted": problem.format(),
    }


def _raise_goals_validation_error(
    *,
    command: str,
    problems: list[GoalsValidationProblem],
    json_output: bool,
) -> None:
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


def _parse_problem_from_exception(exc: Exception) -> GoalsValidationProblem:
    """Build a line-numbered problem from a YAML parser exception."""
    mark = getattr(exc, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    detail = getattr(exc, "problem", None) or "failed to parse YAML"
    return GoalsValidationProblem(
        path="goals.yaml",
        message=str(detail),
        line=(line + 1) if isinstance(line, int) else None,
        column=(column + 1) if isinstance(column, int) else None,
    )


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
