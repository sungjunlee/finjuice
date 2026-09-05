"""Deterministic net worth forecasting with scenarios.yaml inputs.

Pure date and money math helpers live in :mod:`finjuice.pipeline.forecast_helpers`,
mutable portfolio state and its monthly mutations live in
:mod:`finjuice.pipeline.forecast_state`, and lifecycle/opening event apply
helpers live in :mod:`finjuice.pipeline.forecast_events`. All three are
re-exported here so existing call sites keep importing them unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from finjuice.pipeline.forecast_events import (
    ForecastEventHit,
    _apply_lifecycle_events,
    _apply_opening_one_shot_events,
    _monthly_event_is_active,  # noqa: F401 — re-exported for existing forecast imports
    _resolve_target_reached_at,
)
from finjuice.pipeline.forecast_helpers import (
    _add_months,
    _calculate_cagr,
    _days_in_month,  # noqa: F401 — re-exported for existing forecast imports
    _normalize_liability_rate,  # noqa: F401 — re-exported for existing forecast imports
    _round_money,
)
from finjuice.pipeline.forecast_state import (
    _FORECAST_SAVINGS_ASSET_CATEGORY,  # noqa: F401 — re-exported for existing forecast imports
    _FORECAST_SAVINGS_ASSET_NAME,  # noqa: F401 — re-exported for existing forecast imports
    _apply_asset_growth,
    _apply_asset_swap,  # noqa: F401 — re-exported for existing forecast imports
    _apply_cashflow_asset,
    _apply_liability_growth,
    _MutableForecastAsset,
    _MutableForecastLiability,
)
from finjuice.pipeline.forecast_validators import (
    SCENARIO_NAMES,
    SCENARIOS_CONFIG_VERSION,
    AssetSwapEvent,
    LifecycleEvent,
    MonthlyNetExpenseEvent,
    OneTimeExpenseEvent,
    ScenarioAssumptions,
    ScenarioName,
    ScenariosConfig,
    ScenariosConfigIssue,
    ScenariosConfigValidationError,
    ScenariosConfigValidationResult,
    ScenarioValidationIssues,
    validate_scenarios_config_file,
)
from finjuice.pipeline.networth import NetWorthPosition, normalize_asset_name

__all__ = [
    "SCENARIO_NAMES",
    "SCENARIOS_CONFIG_VERSION",
    "AssetSwapEvent",
    "ForecastEventHit",
    "ForecastProjection",
    "ForecastResult",
    "ForecastSummary",
    "LifecycleEvent",
    "MonthlyNetExpenseEvent",
    "OneTimeExpenseEvent",
    "ScenarioAssumptions",
    "ScenarioName",
    "ScenarioValidationIssues",
    "ScenariosConfig",
    "ScenariosConfigIssue",
    "ScenariosConfigValidationError",
    "ScenariosConfigValidationResult",
    "build_forecast",
    "load_scenarios_config",
    "serialize_forecast_result",
    "validate_scenarios_config_file",
]


@dataclass(frozen=True)
class ForecastProjection:
    """One forecast point."""

    date: str
    total_assets: float
    total_liabilities: float
    net_worth: float
    events_fired: list[ForecastEventHit] = field(default_factory=list)


@dataclass(frozen=True)
class ForecastSummary:
    """High-level summary for one scenario."""

    start: str
    end: str
    years: int
    start_net_worth: float
    end_net_worth: float
    cagr: float | None
    events_count: int
    target_net_worth: int | None = None
    target_reached: bool | None = None
    target_reached_at: str | None = None


@dataclass(frozen=True)
class ForecastResult:
    """One scenario forecast output."""

    scenario: ScenarioName
    projections: list[ForecastProjection]
    summary: ForecastSummary


def load_scenarios_config(
    scenarios_file: Path,
    *,
    allow_missing_file: bool = False,
) -> ScenariosConfig:
    """Load and validate scenarios.yaml."""
    result = validate_scenarios_config_file(
        scenarios_file,
        allow_missing_file=allow_missing_file,
    )
    if not result.is_valid:
        raise ScenariosConfigValidationError(scenarios_file, result.issues)
    return result.config


def build_forecast(
    position: NetWorthPosition,
    scenarios_config: ScenariosConfig,
    *,
    scenario: ScenarioName,
    years: int,
    target_net_worth: int | None = None,
) -> ForecastResult:
    """Project one scenario across a fixed monthly horizon."""
    if years < 1:
        raise ValueError("Forecast years must be >= 1")
    if position.as_of is None:
        raise ValueError(
            "Cannot determine forecast start date. Add assets/snapshots or pass --from YYYY-MM-DD."
        )

    current_date = position.as_of
    assets = {
        normalize_asset_name(asset.name): _MutableForecastAsset(
            name=asset.name,
            category=asset.category,
            value=float(asset.value),
        )
        for asset in position.assets
    }
    liabilities = [
        _MutableForecastLiability(
            name=liability.name,
            principal=float(liability.principal),
            rate=liability.rate,
        )
        for liability in position.liabilities
    ]

    fired_once: set[tuple[str, str, str]] = set()
    opening_events = _apply_opening_one_shot_events(
        assets,
        scenarios_config.lifecycle_events,
        opening_date=current_date,
        fired_once=fired_once,
    )
    projections: list[ForecastProjection] = [
        _snapshot_projection(current_date, assets.values(), liabilities, events=opening_events)
    ]

    for _ in range(years * 12):
        next_date = _add_months(current_date, 1)
        _apply_asset_growth(assets.values(), scenarios_config.assumptions, scenario)
        _apply_liability_growth(liabilities, scenarios_config.assumptions)
        _apply_cashflow_asset(
            assets,
            scenarios_config.assumptions.default_savings_per_month,
        )
        events = _apply_lifecycle_events(
            assets,
            liabilities,
            scenarios_config.lifecycle_events,
            previous_date=current_date,
            current_date=next_date,
            fired_once=fired_once,
        )
        projections.append(
            _snapshot_projection(next_date, assets.values(), liabilities, events=events)
        )
        current_date = next_date

    target_reached_at = _resolve_target_reached_at(projections, target_net_worth)
    start_net_worth = projections[0].net_worth
    end_net_worth = projections[-1].net_worth
    summary = ForecastSummary(
        start=projections[0].date,
        end=projections[-1].date,
        years=years,
        start_net_worth=start_net_worth,
        end_net_worth=end_net_worth,
        cagr=_calculate_cagr(start_net_worth, end_net_worth, years),
        events_count=sum(len(point.events_fired) for point in projections),
        target_net_worth=target_net_worth,
        target_reached=(None if target_net_worth is None else target_reached_at is not None),
        target_reached_at=target_reached_at,
    )
    return ForecastResult(
        scenario=scenario,
        projections=projections,
        summary=summary,
    )


def serialize_forecast_result(result: ForecastResult) -> dict[str, Any]:
    """Convert one scenario result into CLI-ready JSON."""
    return {
        "scenario": result.scenario,
        "projections": [
            {
                "date": projection.date,
                "total_assets": projection.total_assets,
                "total_liabilities": projection.total_liabilities,
                "net_worth": projection.net_worth,
                "events_fired": [
                    {
                        "name": event.name,
                        "type": event.type,
                        "effective_date": event.effective_date,
                    }
                    for event in projection.events_fired
                ],
            }
            for projection in result.projections
        ],
        "summary": {
            "start": result.summary.start,
            "end": result.summary.end,
            "years": result.summary.years,
            "start_net_worth": result.summary.start_net_worth,
            "end_net_worth": result.summary.end_net_worth,
            "cagr": result.summary.cagr,
            "events_count": result.summary.events_count,
            "target_net_worth": result.summary.target_net_worth,
            "target_reached": result.summary.target_reached,
            "target_reached_at": result.summary.target_reached_at,
        },
    }


def _snapshot_projection(
    projection_date: date,
    assets: Any,
    liabilities: list[_MutableForecastLiability],
    *,
    events: list[ForecastEventHit],
) -> ForecastProjection:
    """Build one projection row from the mutable asset/liability state."""
    total_assets = _round_money(sum(asset.value for asset in assets))
    total_liabilities = _round_money(sum(liability.principal for liability in liabilities))
    return ForecastProjection(
        date=projection_date.isoformat(),
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth=_round_money(total_assets - total_liabilities),
        events_fired=events,
    )
