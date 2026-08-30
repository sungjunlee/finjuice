"""Identity tests for the forecast helper split."""

from pathlib import Path

from finjuice.pipeline import forecast, forecast_helpers

PIPELINE_DIR = Path("src/finjuice/pipeline")


def test_calendar_and_money_helpers_live_in_helper_module() -> None:
    """Calendar and money helpers should not live in the forecast engine module."""
    forecast_text = (PIPELINE_DIR / "forecast.py").read_text(encoding="utf-8")
    helpers_text = (PIPELINE_DIR / "forecast_helpers.py").read_text(encoding="utf-8")

    assert "def build_forecast" in forecast_text
    assert "def serialize_forecast_result" in forecast_text
    assert "def load_scenarios_config" in forecast_text
    assert "def _apply_lifecycle_events" in forecast_text
    assert "def _snapshot_projection" in forecast_text
    assert "def _add_months" not in forecast_text
    assert "def _days_in_month" not in forecast_text
    assert "def _round_money" not in forecast_text
    assert "def _normalize_liability_rate" not in forecast_text
    assert "def _calculate_cagr" not in forecast_text
    assert "def _add_months" in helpers_text
    assert "def _days_in_month" in helpers_text
    assert "def _round_money" in helpers_text
    assert "def _normalize_liability_rate" in helpers_text
    assert "def _calculate_cagr" in helpers_text


def test_calendar_and_money_helpers_reexport_from_forecast() -> None:
    """Existing forecast imports should keep resolving to the calendar/money helpers."""
    forecast_text = (PIPELINE_DIR / "forecast.py").read_text(encoding="utf-8")

    assert "def build_forecast" in forecast_text
    assert "_add_months" in forecast_text
    assert "_days_in_month" in forecast_text
    assert "_round_money" in forecast_text
    assert "_normalize_liability_rate" in forecast_text
    assert "_calculate_cagr" in forecast_text
    assert forecast._add_months is forecast_helpers._add_months
    assert forecast._days_in_month is forecast_helpers._days_in_month
    assert forecast._round_money is forecast_helpers._round_money
    assert forecast._normalize_liability_rate is forecast_helpers._normalize_liability_rate
    assert forecast._calculate_cagr is forecast_helpers._calculate_cagr
    assert callable(forecast.build_forecast)
    assert callable(forecast.serialize_forecast_result)
    assert callable(forecast.load_scenarios_config)
    assert callable(forecast._apply_lifecycle_events)
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
