"""Deterministic net worth forecasting with scenarios.yaml inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

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

_FORECAST_SAVINGS_ASSET_NAME = "Projected savings"
_FORECAST_SAVINGS_ASSET_CATEGORY = "financial"

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
class ForecastEventHit:
    """One event occurrence captured in a projection row."""

    name: str
    type: str
    effective_date: str


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


@dataclass
class _MutableForecastAsset:
    """Mutable internal asset representation."""

    name: str
    category: str
    value: float


@dataclass
class _MutableForecastLiability:
    """Mutable internal liability representation."""

    name: str
    principal: float
    rate: float | None = None


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


def _apply_asset_growth(
    assets: Any,
    assumptions: ScenarioAssumptions,
    scenario: ScenarioName,
) -> None:
    """Apply one month of asset growth in place."""
    for asset in assets:
        annual_return = assumptions.asset_returns.get(asset.category, {}).get(scenario, 0.0)
        asset.value = _round_money(asset.value * (1.0 + (annual_return / 12.0)))


def _apply_liability_growth(
    liabilities: list[_MutableForecastLiability],
    assumptions: ScenarioAssumptions,
) -> None:
    """Apply one month of liability growth in place."""
    for liability in liabilities:
        rate = _normalize_liability_rate(liability.rate)
        if liability.rate is not None:
            rate += assumptions.liability_rate_delta
        monthly_rate = max(rate, 0.0) / 12.0
        liability.principal = _round_money(liability.principal * (1.0 + monthly_rate))


def _apply_cashflow_asset(
    assets: dict[str, _MutableForecastAsset],
    amount: int,
) -> None:
    """Apply net cashflow into the synthetic projected savings bucket."""
    if amount == 0:
        return

    key = normalize_asset_name(_FORECAST_SAVINGS_ASSET_NAME)
    if key not in assets:
        assets[key] = _MutableForecastAsset(
            name=_FORECAST_SAVINGS_ASSET_NAME,
            category=_FORECAST_SAVINGS_ASSET_CATEGORY,
            value=0.0,
        )
    assets[key].value = _round_money(assets[key].value + float(amount))


def _apply_opening_one_shot_events(
    assets: dict[str, _MutableForecastAsset],
    events: list[LifecycleEvent],
    *,
    opening_date: date,
    fired_once: set[tuple[str, str, str]],
) -> list[ForecastEventHit]:
    """Apply one-shot lifecycle events that land exactly on the forecast start date."""
    hits: list[ForecastEventHit] = []

    for event in events:
        if isinstance(event, OneTimeExpenseEvent):
            marker = ("one_time_expense", event.name, event.date.isoformat())
            if marker in fired_once or event.date != opening_date:
                continue
            _apply_cashflow_asset(assets, -event.one_time_expense)
            fired_once.add(marker)
            hits.append(
                ForecastEventHit(
                    name=event.name,
                    type="one_time_expense",
                    effective_date=event.date.isoformat(),
                )
            )
            continue

        if isinstance(event, AssetSwapEvent):
            marker = ("asset_swap", event.name, event.date.isoformat())
            if marker in fired_once or event.date != opening_date:
                continue
            _apply_asset_swap(assets, event)
            fired_once.add(marker)
            hits.append(
                ForecastEventHit(
                    name=event.name,
                    type="asset_swap",
                    effective_date=event.date.isoformat(),
                )
            )

    return hits


def _apply_lifecycle_events(
    assets: dict[str, _MutableForecastAsset],
    liabilities: list[_MutableForecastLiability],
    events: list[LifecycleEvent],
    *,
    previous_date: date,
    current_date: date,
    fired_once: set[tuple[str, str, str]],
) -> list[ForecastEventHit]:
    """Apply lifecycle events due in the current forecast step."""
    hits: list[ForecastEventHit] = []

    for event in events:
        if isinstance(event, OneTimeExpenseEvent):
            marker = ("one_time_expense", event.name, event.date.isoformat())
            if marker in fired_once or not (previous_date < event.date <= current_date):
                continue
            _apply_cashflow_asset(assets, -event.one_time_expense)
            fired_once.add(marker)
            hits.append(
                ForecastEventHit(
                    name=event.name,
                    type="one_time_expense",
                    effective_date=event.date.isoformat(),
                )
            )
            continue

        if isinstance(event, AssetSwapEvent):
            marker = ("asset_swap", event.name, event.date.isoformat())
            if marker in fired_once or not (previous_date < event.date <= current_date):
                continue
            _apply_asset_swap(assets, event)
            fired_once.add(marker)
            hits.append(
                ForecastEventHit(
                    name=event.name,
                    type="asset_swap",
                    effective_date=event.date.isoformat(),
                )
            )
            continue

        if not _monthly_event_is_active(
            event,
            previous_date=previous_date,
            current_date=current_date,
        ):
            continue
        _apply_cashflow_asset(assets, -event.monthly_net_expense)
        hits.append(
            ForecastEventHit(
                name=event.name,
                type="monthly_net_expense",
                effective_date=current_date.isoformat(),
            )
        )

    return hits


def _apply_asset_swap(
    assets: dict[str, _MutableForecastAsset],
    event: AssetSwapEvent,
) -> None:
    """Replace one asset with another, failing fast when the source asset is missing."""
    remove_key = normalize_asset_name(event.remove)
    if remove_key not in assets:
        raise ValueError(
            f"Asset swap '{event.name}' cannot remove missing asset "
            f"'{event.remove}' on {event.date.isoformat()}."
        )

    assets.pop(remove_key)
    assets[normalize_asset_name(event.add.name)] = _MutableForecastAsset(
        name=event.add.name,
        category=event.add.category,
        value=float(event.add.value),
    )


def _monthly_event_is_active(
    event: MonthlyNetExpenseEvent,
    *,
    previous_date: date,
    current_date: date,
) -> bool:
    """Return True when a recurring event overlaps the current forecast interval."""
    return event.start <= current_date and (event.end is None or event.end > previous_date)


def _resolve_target_reached_at(
    projections: list[ForecastProjection],
    target_net_worth: int | None,
) -> str | None:
    """Return the first projection date that reaches the target."""
    if target_net_worth is None:
        return None
    for projection in projections:
        if projection.net_worth >= target_net_worth:
            return projection.date
    return None


def _calculate_cagr(start_value: float, end_value: float, years: int) -> float | None:
    """Calculate CAGR when the start value is positive."""
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return None
    ratio = end_value / start_value
    return round(float((ratio ** (1.0 / years)) - 1.0), 6)


def _add_months(start_date: date, months: int) -> date:
    """Return *start_date* shifted by a fixed number of months."""
    month_index = (start_date.month - 1) + months
    year = start_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(start_date.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a calendar month."""
    if month == 2:
        is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if is_leap else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31


def _round_money(value: float) -> float:
    """Round money values to two decimals for deterministic output."""
    return round(value, 2)


def _normalize_liability_rate(raw_rate: float | None) -> float:
    """Normalize liability rates expressed as decimals or human percentages."""
    if raw_rate is None:
        return 0.0
    return raw_rate / 100.0 if abs(raw_rate) > 1.0 else raw_rate
