"""Identity tests for the forecast_validators/validate helper split."""

from pathlib import Path

from finjuice.pipeline.forecast_validators import lifecycle, validate

FORECAST_VALIDATORS_DIR = Path("src/finjuice/pipeline/forecast_validators")


def test_lifecycle_helpers_live_in_helper_module() -> None:
    """Lifecycle-event section validators should not live in validate.py."""
    validate_text = (FORECAST_VALIDATORS_DIR / "validate.py").read_text(encoding="utf-8")
    lifecycle_text = (FORECAST_VALIDATORS_DIR / "lifecycle.py").read_text(encoding="utf-8")

    assert "def validate_scenarios_config_file" in validate_text
    assert "def _validate_scenarios_payload" in validate_text
    assert "def _validate_assumptions" in validate_text
    assert "def _validate_lifecycle_events" not in validate_text
    assert "def _validate_lifecycle_event" not in validate_text
    assert "def _select_lifecycle_event_shape" not in validate_text
    assert "def _validate_one_time_expense_event" not in validate_text
    assert "def _validate_monthly_net_expense_event" not in validate_text
    assert "def _validate_asset_swap_event" not in validate_text
    assert "def _validate_asset_swap(" not in validate_text
    assert "def _validate_lifecycle_events" in lifecycle_text
    assert "def _validate_lifecycle_event" in lifecycle_text
    assert "def _select_lifecycle_event_shape" in lifecycle_text
    assert "def _validate_one_time_expense_event" in lifecycle_text
    assert "def _validate_monthly_net_expense_event" in lifecycle_text
    assert "def _validate_asset_swap_event" in lifecycle_text
    assert "def _validate_asset_swap(" in lifecycle_text


def test_lifecycle_helpers_reexport_from_validate() -> None:
    """Existing validate.py imports should keep resolving to the lifecycle helpers."""
    assert validate._validate_lifecycle_events is lifecycle._validate_lifecycle_events
    assert validate._validate_lifecycle_event is lifecycle._validate_lifecycle_event
    assert validate._select_lifecycle_event_shape is lifecycle._select_lifecycle_event_shape
    assert validate._validate_one_time_expense_event is lifecycle._validate_one_time_expense_event
    assert validate._validate_monthly_net_expense_event is (
        lifecycle._validate_monthly_net_expense_event
    )
    assert validate._validate_asset_swap_event is lifecycle._validate_asset_swap_event
    assert validate._validate_asset_swap is lifecycle._validate_asset_swap
    assert validate._ASSET_SWAP_KEYS is lifecycle._ASSET_SWAP_KEYS
    assert validate._ASSET_SWAP_ADD_KEYS is lifecycle._ASSET_SWAP_ADD_KEYS
    assert callable(validate.validate_scenarios_config_file)
    assert callable(validate._validate_assumptions)
    assert callable(validate._validate_asset_returns)
