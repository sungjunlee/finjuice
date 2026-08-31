"""Structure tests for the forecast.py portfolio-state helper split.

Mutable portfolio state containers and monthly mutation helpers live in
``forecast_state`` and must stay identity-equal when re-exported from
``forecast``, so existing import paths and monkeypatches keep working after
the split. The split also keeps ``forecast_state`` as the single canonical
home for the moved cluster.
"""

from __future__ import annotations

import importlib


def test_forecast_reexports_portfolio_state_identity() -> None:
    """Portfolio state and mutation helpers stay on forecast as re-exports."""
    forecast = importlib.import_module("finjuice.pipeline.forecast")
    state = importlib.import_module("finjuice.pipeline.forecast_state")

    assert forecast._FORECAST_SAVINGS_ASSET_NAME is state._FORECAST_SAVINGS_ASSET_NAME
    assert forecast._FORECAST_SAVINGS_ASSET_CATEGORY is state._FORECAST_SAVINGS_ASSET_CATEGORY
    assert forecast._MutableForecastAsset is state._MutableForecastAsset
    assert forecast._MutableForecastLiability is state._MutableForecastLiability
    assert forecast._apply_asset_growth is state._apply_asset_growth
    assert forecast._apply_liability_growth is state._apply_liability_growth
    assert forecast._apply_cashflow_asset is state._apply_cashflow_asset
    assert forecast._apply_asset_swap is state._apply_asset_swap


def test_forecast_state_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in forecast_state."""
    state = importlib.import_module("finjuice.pipeline.forecast_state")
    canonical = "finjuice.pipeline.forecast_state"

    assert state._MutableForecastAsset.__module__ == canonical
    assert state._MutableForecastLiability.__module__ == canonical
    assert state._apply_asset_growth.__module__ == canonical
    assert state._apply_liability_growth.__module__ == canonical
    assert state._apply_cashflow_asset.__module__ == canonical
    assert state._apply_asset_swap.__module__ == canonical
