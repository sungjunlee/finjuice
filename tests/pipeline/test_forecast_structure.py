"""Structure tests for the forecast.py helper split.

Pure date and money math helpers live in ``forecast_helpers`` and must stay
identity-equal when re-exported from ``forecast``, so existing import paths
and monkeypatches keep working after the split.
"""

from __future__ import annotations

import importlib


def test_forecast_reexports_math_helpers_identity() -> None:
    """Date/money math helpers stay on forecast as re-exports after the split."""
    forecast = importlib.import_module("finjuice.pipeline.forecast")
    helpers = importlib.import_module("finjuice.pipeline.forecast_helpers")

    assert forecast._add_months is helpers._add_months
    assert forecast._calculate_cagr is helpers._calculate_cagr
    assert forecast._days_in_month is helpers._days_in_month
    assert forecast._normalize_liability_rate is helpers._normalize_liability_rate
    assert forecast._round_money is helpers._round_money


def test_forecast_public_api_unchanged_by_helper_split() -> None:
    """The forecast module keeps its documented public API surface."""
    forecast = importlib.import_module("finjuice.pipeline.forecast")

    assert forecast.__all__ == [
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
