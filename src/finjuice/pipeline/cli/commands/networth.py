"""Aggregated net worth CLI commands."""

from __future__ import annotations

import importlib.resources
import json
import logging
from datetime import date
from typing import Any, Literal, cast

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    _build_meta,
    console,
    emit_error,
    info,
    section,
    success,
    table_summary,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.forecast import (
    SCENARIO_NAMES,
    ScenariosConfigValidationError,
    build_forecast,
    load_scenarios_config,
    serialize_forecast_result,
)
from finjuice.pipeline.goals import GoalsValidationProblem, load_goals_file
from finjuice.pipeline.networth import (
    AssetsConfigValidationError,
    build_breakdown_rows,
    build_networth_position,
    list_history_snapshots,
    load_assets_config,
    merge_asset_sources,
    snapshot_assets_from_selection,
    validate_assets_config_file,
)

logger = logging.getLogger(__name__)

networth_app = typer.Typer(
    name="networth",
    help=(
        "View aggregated net worth from asset snapshots plus assets.yaml. "
        "Use `finjuice assets` for raw snapshot rows."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)


def _format_krw(amount: float) -> str:
    """Format amount as KRW."""
    sign = "-" if amount < 0 else ""
    return f"{sign}₩{abs(amount):,.0f}"


def _parse_as_of(raw_value: str | None) -> date | None:
    """Parse an ISO date option."""
    if raw_value is None:
        return None
    return date.fromisoformat(raw_value)


def _resolve_as_of(ctx: typer.Context, date_value: str | None) -> date | None:
    """Resolve the effective as-of date for networth subcommands."""
    if date_value is not None:
        return _parse_as_of(date_value)

    parent_ctx = ctx.parent
    if parent_ctx is None:
        return None

    parent_date_value = parent_ctx.params.get("date_value")
    if parent_date_value is None:
        return None

    return _parse_as_of(str(parent_date_value))


def _emit_networth_json(
    payload: dict[str, Any],
    *,
    command: str,
    as_of: str | None,
    filters_applied: int,
    extras: dict[str, Any] | None = None,
) -> None:
    """Emit JSON with the custom networth envelope."""
    meta_extras = {
        "filters_applied": filters_applied,
        "as_of": as_of,
    }
    if extras:
        meta_extras.update(extras)
    meta = _build_meta(command, extras=meta_extras)
    typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))


def _build_networth_guidance(
    *,
    assets: list[Any],
    liabilities: list[Any],
    net_worth: float,
) -> dict[str, Any]:
    """Build additive health/action cues for top-level networth JSON."""
    has_snapshot_data = any(getattr(asset, "source", None) == "snapshot" for asset in assets)
    has_manual_assets = any(getattr(asset, "source", None) == "manual" for asset in assets)
    has_liabilities = bool(liabilities)

    if has_snapshot_data and has_manual_assets:
        snapshot_status = "snapshot_and_manual"
    elif has_snapshot_data:
        snapshot_status = "snapshot_only"
    elif has_manual_assets:
        snapshot_status = "manual_only"
    elif has_liabilities:
        snapshot_status = "liabilities_only"
    else:
        snapshot_status = "empty"

    reasons: list[str] = []
    if snapshot_status in {"manual_only", "liabilities_only"}:
        reasons.append("snapshot_missing")
    elif snapshot_status == "snapshot_only":
        reasons.append("snapshot_only")
    elif snapshot_status == "empty":
        reasons.append("no_asset_data")

    if net_worth < 0:
        reasons.append("negative_net_worth")

    next_steps: list[dict[str, str]] = []
    if snapshot_status in {"snapshot_only", "manual_only", "liabilities_only", "empty"}:
        message = (
            "Add manual assets or liabilities if snapshots do not cover the full balance sheet."
            if snapshot_status == "snapshot_only"
            else "Capture an asset snapshot or confirm assets.yaml coverage."
        )
        next_steps.append(
            {
                "signal": reasons[0],
                "message": message,
                "command": "finjuice assets status --json",
            }
        )
    if net_worth < 0:
        next_steps.append(
            {
                "signal": "negative_net_worth",
                "message": "Inspect the balance-sheet mix behind the negative position.",
                "command": "finjuice networth breakdown --by category --json",
            }
        )

    return {
        "health": {
            "status": "critical" if snapshot_status == "empty" else "warning" if reasons else "ok",
            "reasons": reasons,
        },
        "actionable": bool(reasons),
        "signals": {
            "snapshot_status": snapshot_status,
            "has_snapshot_data": has_snapshot_data,
            "has_manual_assets": has_manual_assets,
            "has_liabilities": has_liabilities,
            "asset_count": len(assets),
            "liability_count": len(liabilities),
            "net_worth_negative": net_worth < 0,
        },
        "next_steps": next_steps,
    }


def _build_networth_result(
    ctx: typer.Context,
    *,
    as_of: date | None,
    json_output: bool,
    command: str,
) -> dict[str, Any]:
    """Build the aggregated net worth payload."""
    config = get_config(ctx)
    position = build_networth_position(
        config.data_dir / "assets" / "snapshots",
        config.assets_file,
        as_of=as_of,
    )
    resolved_as_of = position.as_of.isoformat() if position.as_of is not None else None

    return {
        "as_of": resolved_as_of,
        "total_assets": position.total_assets,
        "total_liabilities": position.total_liabilities,
        "net_worth": position.net_worth,
        **_build_networth_guidance(
            assets=position.assets,
            liabilities=position.liabilities,
            net_worth=position.net_worth,
        ),
        "_assets": position.assets,
        "_liabilities": position.liabilities,
        "_filters_applied": 0,
    }


def _render_overview(result: dict[str, Any]) -> None:
    """Render the top-level net worth summary."""
    section("Net Worth")
    table_summary(
        "Aggregated Position",
        [
            ("As Of", result["as_of"] or "-"),
            ("Total Assets", _format_krw(result["total_assets"])),
            ("Total Liabilities", _format_krw(result["total_liabilities"])),
            ("Net Worth", _format_krw(result["net_worth"])),
        ],
    )

    if not result["_assets"] and not result["_liabilities"]:
        info("자산 스냅샷과 assets.yaml 항목이 없어 총액은 0원입니다.")
        return

    success(
        f"Aggregated {len(result['_assets'])} assets and {len(result['_liabilities'])} liabilities"
    )


def _render_breakdown(as_of: str | None, rows: list[dict[str, Any]], *, by: str) -> None:
    """Render a breakdown table."""
    section("Net Worth Breakdown")

    if not rows:
        info("집계할 자산이 없습니다.")
        return

    table = Table(title=f"As Of {as_of or '-'}")
    table.add_column("Category" if by == "category" else "Asset", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_column("Share", justify="right")

    label_key = "category" if by == "category" else "asset_name"
    for row in rows:
        table.add_row(
            str(row[label_key]),
            _format_krw(float(row["value"])),
            f"{float(row['share_pct']):.2f}%",
        )

    console.print(table)
    success(f"{len(rows)} breakdown rows")


def _render_history(rows: list[dict[str, Any]]) -> None:
    """Render history rows."""
    section("Net Worth History")

    if not rows:
        info(
            "가용한 자산 스냅샷 이력이 없습니다."
            " 자산 스냅샷을 추가하려면 finjuice assets status 를 확인하거나"
            " assets.yaml 을 생성하세요."
        )
        return

    table = Table(title="Monthly Snapshot History")
    table.add_column("As Of", style="cyan")
    table.add_column("Net Worth", justify="right", style="green")
    for row in rows:
        table.add_row(str(row["as_of"]), _format_krw(float(row["net_worth"])))

    console.print(table)
    success(f"{len(rows)} historical points")


def _render_forecast(result: dict[str, Any]) -> None:
    """Render one scenario forecast result."""
    summary = result["summary"]
    section("Net Worth Forecast")
    summary_rows = [
        ("Scenario", str(result["scenario"])),
        ("Start", str(summary["start"])),
        ("End", str(summary["end"])),
        ("Years", str(summary["years"])),
        ("Start Net Worth", _format_krw(float(summary["start_net_worth"]))),
        ("End Net Worth", _format_krw(float(summary["end_net_worth"]))),
        (
            "CAGR",
            "-" if summary["cagr"] is None else f"{float(summary['cagr']) * 100:.2f}%",
        ),
        ("Events Fired", str(summary["events_count"])),
    ]
    if summary.get("target_net_worth") is not None:
        summary_rows.append(("Target", _format_krw(float(summary["target_net_worth"]))))
        reached_label = summary.get("target_reached_at") if summary.get("target_reached") else "No"
        summary_rows.append(("Reached", str(reached_label)))
    table_summary("Scenario Summary", summary_rows)

    checkpoints = _select_projection_rows(result["projections"])
    if not checkpoints:
        info("투영할 데이터가 없습니다.")
        return

    table = Table(title="Projection Checkpoints")
    table.add_column("Date", style="cyan")
    table.add_column("Net Worth", justify="right", style="green")
    table.add_column("Assets", justify="right")
    table.add_column("Liabilities", justify="right")
    table.add_column("Events")

    for row in checkpoints:
        events = ", ".join(event["name"] for event in row["events_fired"]) or "-"
        table.add_row(
            str(row["date"]),
            _format_krw(float(row["net_worth"])),
            _format_krw(float(row["total_assets"])),
            _format_krw(float(row["total_liabilities"])),
            events,
        )

    console.print(table)
    success(f"{len(result['projections'])} forecast points")


def _render_forecast_comparison(
    scenarios: dict[str, dict[str, Any]],
    *,
    years: int,
) -> None:
    """Render the multi-scenario comparison view."""
    show_goal_status = any(
        scenario_result["summary"].get("target_net_worth") is not None
        for scenario_result in scenarios.values()
    )
    section("Net Worth Forecast")
    table = Table(title=f"Scenario Comparison ({years}y)")
    table.add_column("Scenario", style="cyan")
    table.add_column("End Net Worth", justify="right", style="green")
    table.add_column("CAGR", justify="right")
    if show_goal_status:
        table.add_column("Reached", justify="center")
    table.add_column("Events", justify="right")

    for scenario_name in SCENARIO_NAMES:
        scenario_result = scenarios[scenario_name]
        summary = scenario_result["summary"]
        row = [
            scenario_name,
            _format_krw(float(summary["end_net_worth"])),
            "-" if summary["cagr"] is None else f"{float(summary['cagr']) * 100:.2f}%",
        ]
        if show_goal_status:
            reached_label = (
                summary.get("target_reached_at") if summary.get("target_reached") else "No"
            )
            row.append(str(reached_label))
        row.append(str(summary["events_count"]))
        table.add_row(*row)

    console.print(table)
    success(f"Compared {len(scenarios)} scenarios")


def _render_validate(result: dict[str, Any]) -> None:
    """Render assets.yaml validation output."""
    section("assets.yaml Validation")

    if not result["exists"]:
        info("assets.yaml 없음. networth는 자산 스냅샷만으로 계속 동작합니다.")
        return

    if result["valid"]:
        table_summary(
            "Schema Summary",
            [
                ("Version", str(result["version"])),
                ("Manual Assets", str(result["manual_assets"])),
                ("Liabilities", str(result["liabilities"])),
            ],
        )
        success("assets.yaml is valid")
        return

    for issue in result["problems"]:
        console.print(f"[red]❌ {issue['formatted']}[/red]")


def _validation_issue_to_problem(issue: Any) -> dict[str, Any]:
    """Convert an assets.yaml validation issue to the shared validation envelope."""
    return {
        "severity": "error",
        "type": "invalid_assets_config",
        "path": issue.path,
        "message": issue.message,
        "line": issue.line,
        "column": issue.column,
        "formatted": issue.format(),
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


def _handle_networth_exception(
    exc: Exception,
    *,
    json_output: bool,
    command: str,
) -> None:
    """Convert runtime networth errors into CLI envelopes."""
    if isinstance(exc, AssetsConfigValidationError):
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    if isinstance(exc, ScenariosConfigValidationError):
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    if isinstance(exc, ValueError):
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command,
        )

    emit_error(
        f"Failed to compute net worth: {exc}",
        error_code=ErrorCode.GENERAL_ERROR,
        json_output=json_output,
        command=command,
    )


@networth_app.callback(invoke_without_command=True)
def networth_callback(
    ctx: typer.Context,
    date_value: str | None = typer.Option(None, "--date", help="Snapshot date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show aggregated net worth from snapshots + assets.yaml."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        result = _build_networth_result(
            ctx,
            as_of=_parse_as_of(date_value),
            json_output=json_output,
            command="networth",
        )
        json_result = {key: value for key, value in result.items() if not key.startswith("_")}
        if json_output:
            _emit_networth_json(
                json_result,
                command="networth",
                as_of=result["as_of"],
                filters_applied=result["_filters_applied"],
            )
            return
        _render_overview(result)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth: %s", exc, exc_info=True)
        _handle_networth_exception(exc, json_output=json_output, command="networth")


@networth_app.command()
def breakdown(
    ctx: typer.Context,
    by: Literal["category", "asset"] = typer.Option(
        ...,
        "--by",
        help="Break down by category or asset",
    ),
    date_value: str | None = typer.Option(None, "--date", help="Snapshot date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show aggregated asset breakdown by category or asset."""
    try:
        result = _build_networth_result(
            ctx,
            as_of=_resolve_as_of(ctx, date_value),
            json_output=json_output,
            command="networth breakdown",
        )
        rows = build_breakdown_rows(result["_assets"], by=by)
        payload = {
            "as_of": result["as_of"],
            "breakdown": rows,
        }
        if json_output:
            _emit_networth_json(
                payload,
                command="networth breakdown",
                as_of=result["as_of"],
                filters_applied=result["_filters_applied"],
            )
            return
        _render_breakdown(result["as_of"], rows, by=by)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth breakdown: %s", exc, exc_info=True)
        _handle_networth_exception(exc, json_output=json_output, command="networth breakdown")


@networth_app.command()
def history(
    ctx: typer.Context,
    months: int = typer.Option(6, "--months", min=1, help="Max monthly points to return"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show monthly net worth history from available snapshots."""
    command = "networth history"
    try:
        config = get_config(ctx)
        assets_config = load_assets_config(config.assets_file, allow_missing_file=True)

        rows: list[dict[str, Any]] = []
        for snapshot in list_history_snapshots(config.data_dir / "assets" / "snapshots", months):
            assets = merge_asset_sources(
                snapshot_assets_from_selection(snapshot),
                assets_config.manual_assets,
            )
            total_assets = sum(asset.value for asset in assets)
            total_liabilities = sum(liability.principal for liability in assets_config.liabilities)
            rows.append(
                {
                    "as_of": snapshot.snapshot_date.isoformat(),
                    "net_worth": total_assets - total_liabilities,
                }
            )

        as_of = rows[-1]["as_of"] if rows else None
        payload = {"history": rows}
        if json_output:
            _emit_networth_json(
                payload,
                command=command,
                as_of=as_of,
                filters_applied=0,
            )
            return
        _render_history(rows)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth history: %s", exc, exc_info=True)
        _handle_networth_exception(exc, json_output=json_output, command=command)


@networth_app.command()
def forecast(
    ctx: typer.Context,
    years: int = typer.Option(5, "--years", min=1, max=100, help="Forecast horizon in years"),
    scenario: Literal["conservative", "neutral", "optimistic", "all"] = typer.Option(
        "neutral",
        "--scenario",
        help="Scenario: conservative, neutral, optimistic, all",
    ),
    from_value: str | None = typer.Option(None, "--from", help="Forecast start date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Project net worth under deterministic scenario assumptions."""
    command = "networth forecast"
    try:
        config = get_config(ctx)
        start_date = _resolve_as_of(ctx, from_value)
        position = build_networth_position(
            config.data_dir / "assets" / "snapshots",
            config.assets_file,
            as_of=start_date,
        )
        scenarios_config = load_scenarios_config(config.scenarios_file)
        goals_result = load_goals_file(config.goals_file)
        if goals_result.problems:
            _raise_goals_validation_error(
                command=command,
                problems=goals_result.problems,
                json_output=json_output,
            )
        target_net_worth = (
            goals_result.document.net_worth_target if goals_result.document is not None else None
        )

        if scenario == "all":
            scenario_payloads = {
                scenario_name: serialize_forecast_result(
                    build_forecast(
                        position,
                        scenarios_config,
                        scenario=cast(
                            Literal["conservative", "neutral", "optimistic"],
                            scenario_name,
                        ),
                        years=years,
                        target_net_worth=target_net_worth,
                    )
                )
                for scenario_name in SCENARIO_NAMES
            }
            payload = {"scenarios": scenario_payloads}
            start_as_of = position.as_of.isoformat() if position.as_of is not None else None
            total_events = sum(
                scenario_payload["summary"]["events_count"]
                for scenario_payload in scenario_payloads.values()
            )
            if json_output:
                _emit_networth_json(
                    payload,
                    command=command,
                    as_of=start_as_of,
                    filters_applied=0,
                    extras={
                        "scenario": "all",
                        "years": years,
                        "start_date": start_as_of,
                        "events_fired": total_events,
                    },
                )
                return
            _render_forecast_comparison(scenario_payloads, years=years)
            return

        selected_scenario = cast(Literal["conservative", "neutral", "optimistic"], scenario)
        result = serialize_forecast_result(
            build_forecast(
                position,
                scenarios_config,
                scenario=selected_scenario,
                years=years,
                target_net_worth=target_net_worth,
            )
        )
        start_as_of = position.as_of.isoformat() if position.as_of is not None else None
        if json_output:
            _emit_networth_json(
                result,
                command=command,
                as_of=start_as_of,
                filters_applied=0,
                extras={
                    "scenario": scenario,
                    "years": years,
                    "start_date": result["summary"]["start"],
                    "events_fired": result["summary"]["events_count"],
                },
            )
            return
        _render_forecast(result)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to compute net worth forecast: %s", exc, exc_info=True)
        _handle_networth_exception(exc, json_output=json_output, command=command)


@networth_app.command("init")
def init_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create a starter assets.yaml from the built-in template."""
    config = get_config(ctx)
    dest_path = config.assets_file

    if dest_path.exists():
        payload = {
            "path": str(dest_path),
            "created": False,
            "message": f"assets.yaml already exists at {dest_path}",
        }
        if json_output:
            typer.echo(
                json.dumps(
                    {"_meta": _build_meta("networth init"), **payload},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            info(f"assets.yaml already exists at {dest_path}")
            info("Run 'finjuice networth validate' to check, or 'finjuice networth' to view.")
        return

    try:
        template_files = importlib.resources.files("finjuice.templates")
        template = template_files.joinpath("assets.yaml.example").read_text(encoding="utf-8")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(template, encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to create assets.yaml: %s", exc, exc_info=True)
        emit_error(
            f"Failed to create assets.yaml: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="networth init",
        )

    payload = {
        "path": str(dest_path),
        "created": True,
        "message": f"Created starter assets.yaml at {dest_path}",
    }
    if json_output:
        typer.echo(
            json.dumps(
                {"_meta": _build_meta("networth init"), **payload},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        success(f"Created {dest_path}")
        info("Edit the values and run 'finjuice networth validate' to verify.")
        info("Then run 'finjuice networth' to see your position.")


@networth_app.command("validate")
def validate_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate assets.yaml and report line-numbered errors."""
    config = get_config(ctx)
    validation = validate_assets_config_file(config.assets_file, allow_missing_file=True)
    problems = [_validation_issue_to_problem(issue) for issue in validation.issues]
    payload = {
        "path": str(config.assets_file),
        "exists": validation.exists,
        "valid": validation.is_valid,
        "status": "valid" if validation.is_valid else "issues",
        "version": validation.config.version if validation.exists and validation.is_valid else None,
        "manual_assets": len(validation.config.manual_assets) if validation.is_valid else 0,
        "liabilities": len(validation.config.liabilities) if validation.is_valid else 0,
        "errors": len(problems),
        "warnings": 0,
        "problems": problems,
    }

    if json_output:
        typer.echo(
            json.dumps(
                {"_meta": _build_meta("networth validate"), **payload},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _render_validate(payload)

    if not validation.is_valid:
        raise typer.Exit(code=1)


def _select_projection_rows(projections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep text output readable for long forecast horizons."""
    if len(projections) <= 24:
        return projections

    selected: list[dict[str, Any]] = [projections[0]]
    last_index = len(projections) - 1
    for index, row in enumerate(projections[1:], start=1):
        if index == last_index or index % 12 == 0 or row["events_fired"]:
            selected.append(row)
    return selected
