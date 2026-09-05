"""Aggregated net worth CLI commands.

JSON payload assembly helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_payload` and are re-exported
here so existing callers can keep importing from this module. Forecast
scenario serialization helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_forecast`. Monthly history-row
helpers live in :mod:`finjuice.pipeline.cli.commands.networth_history`. JSON
health/action guidance helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_guidance`. Validation and
runtime error envelopes live in
:mod:`finjuice.pipeline.cli.commands.networth_errors`. assets.yaml
init/validate helpers live in
:mod:`finjuice.pipeline.cli.commands.networth_helpers`.
"""

from __future__ import annotations

import logging
from typing import Literal, cast

import typer

from finjuice.pipeline.asset_config import load_assets_config
from finjuice.pipeline.cli.commands.networth_errors import (
    _handle_networth_exception,
    _raise_goals_validation_error,
    _validation_issue_to_problem,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_forecast import (
    _build_all_scenario_forecasts,
    _forecast_start_as_of,
    _serialize_forecast_scenario,
)
from finjuice.pipeline.cli.commands.networth_guidance import (
    _build_networth_guidance,  # noqa: F401 — re-exported for existing networth imports
    _build_networth_signals,  # noqa: F401 — re-exported for existing networth imports
    _build_source_flags,  # noqa: F401 — re-exported for existing networth imports
    _resolve_snapshot_status,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_helpers import (
    _assets_init_payload,  # noqa: F401 — re-exported for existing networth imports
    _build_validate_payload,  # noqa: F401 — re-exported for existing networth imports
    _emit_assets_file_json,  # noqa: F401 — re-exported for existing networth imports
    _run_init_command,
    _run_validate_command,
    _write_starter_assets_yaml,  # noqa: F401 — re-exported for existing networth imports
)
from finjuice.pipeline.cli.commands.networth_history import (
    _build_history_rows,
    _history_as_of,
)
from finjuice.pipeline.cli.commands.networth_payload import (
    _build_networth_result,
    _emit_networth_json,
    _parse_as_of,
    _resolve_as_of,
)
from finjuice.pipeline.cli.commands.networth_rendering import (
    _render_breakdown,
    _render_forecast,
    _render_forecast_comparison,
    _render_history,
    _render_overview,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.forecast import load_scenarios_config
from finjuice.pipeline.goals import load_goals_file
from finjuice.pipeline.networth import (
    build_breakdown_rows,
    build_networth_position,
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
        rows = _build_history_rows(
            config.data_dir / "assets" / "snapshots",
            assets_config,
            months=months,
        )
        as_of = _history_as_of(rows)
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
            balance_dir=config.data_dir / "banksalad" / "balance",
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
            scenario_payloads = _build_all_scenario_forecasts(
                position,
                scenarios_config,
                years=years,
                target_net_worth=target_net_worth,
            )
            payload = {"scenarios": scenario_payloads}
            start_as_of = _forecast_start_as_of(position)
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
        result = _serialize_forecast_scenario(
            position,
            scenarios_config,
            scenario=selected_scenario,
            years=years,
            target_net_worth=target_net_worth,
        )
        start_as_of = _forecast_start_as_of(position)
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
    _run_init_command(ctx, json_output=json_output)


@networth_app.command("validate")
def validate_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate assets.yaml and report line-numbered errors."""
    _run_validate_command(ctx, json_output=json_output)
