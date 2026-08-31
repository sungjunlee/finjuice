"""Mutable portfolio state and monthly mutation helpers for the forecast engine.

The forecast projection loop keeps an in-memory asset/liability portfolio and
mutates it one month at a time. The mutable containers and the in-place asset
growth, liability growth, cashflow, and asset-swap mutations live here so
:mod:`finjuice.pipeline.forecast` stays focused on scenario projection
orchestration. The helpers are re-exported from that module so existing call
sites keep importing them unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.forecast_helpers import _normalize_liability_rate, _round_money
from finjuice.pipeline.forecast_validators import (
    AssetSwapEvent,
    ScenarioAssumptions,
    ScenarioName,
)
from finjuice.pipeline.networth import normalize_asset_name

_FORECAST_SAVINGS_ASSET_NAME = "Projected savings"
_FORECAST_SAVINGS_ASSET_CATEGORY = "financial"


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
