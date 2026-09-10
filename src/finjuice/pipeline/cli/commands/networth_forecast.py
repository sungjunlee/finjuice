"""Forecast scenario serialization helpers for ``finjuice networth``.

Owns single-scenario serialization, the all-scenario comparison payload,
forecast start-date formatting, and the forecast command callback.
Typer parsers stay in :mod:`finjuice.pipeline.cli.commands.networth`,
which re-exports the names used by existing callers.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

import typer

from finjuice.pipeline.cli.commands.networth_errors import (
    _handle_networth_exception,
    _raise_goals_validation_error,
)
from finjuice.pipeline.cli.commands.networth_payload import (
    _emit_networth_json,
    _resolve_as_of,
)
from finjuice.pipeline.cli.commands.networth_rendering import (
    _render_forecast,
    _render_forecast_comparison,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.forecast import (
    SCENARIO_NAMES,
    ScenarioName,
    ScenariosConfig,
    build_forecast,
    load_scenarios_config,
    serialize_forecast_result,
)
from finjuice.pipeline.goals import load_goals_file
from finjuice.pipeline.networth import NetWorthPosition, build_networth_position

logger = logging.getLogger(__name__)


def _forecast_start_as_of(position: NetWorthPosition) -> str | None:
    """Return the ISO start date for a forecast position."""
    return position.as_of.isoformat() if position.as_of is not None else None


def _serialize_forecast_scenario(
    position: NetWorthPosition,
    scenarios_config: ScenariosConfig,
    *,
    scenario: ScenarioName,
    years: int,
    target_net_worth: int | None,
) -> dict[str, Any]:
    """Serialize one deterministic scenario into the CLI forecast payload."""
    return serialize_forecast_result(
        build_forecast(
            position,
            scenarios_config,
            scenario=scenario,
            years=years,
            target_net_worth=target_net_worth,
        )
    )


def _build_all_scenario_forecasts(
    position: NetWorthPosition,
    scenarios_config: ScenariosConfig,
    *,
    years: int,
    target_net_worth: int | None,
) -> dict[str, dict[str, Any]]:
    """Serialize conservative, neutral, and optimistic forecast payloads."""
    return {
        scenario_name: _serialize_forecast_scenario(
            position,
            scenarios_config,
            scenario=cast(ScenarioName, scenario_name),
            years=years,
            target_net_worth=target_net_worth,
        )
        for scenario_name in SCENARIO_NAMES
    }


def _run_forecast_command(
    ctx: typer.Context,
    *,
    years: int,
    scenario: Literal["conservative", "neutral", "optimistic", "all"],
    from_value: str | None,
    json_output: bool,
) -> None:
    """Run the ``finjuice networth forecast`` command body."""
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
