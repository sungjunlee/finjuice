"""Lifecycle and opening-event apply helpers for the forecast engine.

Opening one-shot events, in-horizon lifecycle events, monthly-event activity,
and target-reached date resolution live here so
:mod:`finjuice.pipeline.forecast` stays focused on scenario projection
orchestration. The helpers are re-exported from that module so existing call
sites keep importing them unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from finjuice.pipeline.forecast_state import (
    _apply_asset_swap,
    _apply_cashflow_asset,
    _MutableForecastAsset,
    _MutableForecastLiability,
)
from finjuice.pipeline.forecast_validators import (
    AssetSwapEvent,
    LifecycleEvent,
    MonthlyNetExpenseEvent,
    OneTimeExpenseEvent,
)

if TYPE_CHECKING:
    from finjuice.pipeline.forecast import ForecastProjection


@dataclass(frozen=True)
class ForecastEventHit:
    """One event occurrence captured in a projection row."""

    name: str
    type: str
    effective_date: str


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
