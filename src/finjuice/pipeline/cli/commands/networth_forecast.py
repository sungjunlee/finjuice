"""Forecast scenario serialization helpers for ``finjuice networth``.

Owns single-scenario serialization, the all-scenario comparison payload,
and forecast start-date formatting. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

from typing import Any, cast

from finjuice.pipeline.forecast import (
    SCENARIO_NAMES,
    ScenarioName,
    ScenariosConfig,
    build_forecast,
    serialize_forecast_result,
)
from finjuice.pipeline.networth import NetWorthPosition


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
