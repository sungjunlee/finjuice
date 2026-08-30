"""Focused tests for scenarios.yaml validator contracts."""

from pathlib import Path

from finjuice.pipeline.forecast_validators import (
    AssetSwapEvent,
    ScenariosConfigValidationResult,
    validate_scenarios_config_file,
)
from finjuice.pipeline.forecast_validators.fields import (
    _add_issue as fields_add_issue,
)
from finjuice.pipeline.forecast_validators.fields import (
    _build_path_locations as fields_build_path_locations,
)
from finjuice.pipeline.forecast_validators.fields import (
    _require_string as fields_require_string,
)
from finjuice.pipeline.forecast_validators.validate import (
    _add_issue,
    _build_path_locations,
    _require_string,
)

FORECAST_VALIDATORS_DIR = Path("src/finjuice/pipeline/forecast_validators")


def _write_scenarios(path: Path, lifecycle_events: str, *, liability_delta: str = "0.0") -> None:
    path.write_text(
        f"""version: 1
assumptions:
  default_savings_per_month: 0
  asset_returns:
    real_estate:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    financial:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    deposit:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    cash:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
  liability_rate_delta: {liability_delta}
lifecycle_events:
{lifecycle_events}
""",
        encoding="utf-8",
    )


def test_validate_scenarios_config_accepts_same_month_sell_then_buy_swaps(
    tmp_path: Path,
) -> None:
    """Same-month sell-then-buy lifecycle swaps should remain a valid shape."""
    scenarios_file = tmp_path / "scenarios.yaml"
    _write_scenarios(
        scenarios_file,
        """  - name: Sell Home
    date: 2026-02-01
    asset_swap:
      remove: Home
      add:
        name: Sale Cash
        category: cash
        value: 700000000
  - name: Buy Deposit
    date: 2026-02-15
    asset_swap:
      remove: Sale Cash
      add:
        name: Deposit A
        category: deposit
        value: 700000000
""",
        liability_delta="-0.01",
    )

    result = validate_scenarios_config_file(scenarios_file)

    assert isinstance(result, ScenariosConfigValidationResult)
    assert result.issues == []
    assert result.config.assumptions.liability_rate_delta == -0.01
    assert len(result.config.lifecycle_events) == 2
    assert all(isinstance(event, AssetSwapEvent) for event in result.config.lifecycle_events)
    assert result.config.lifecycle_events[0].date.isoformat() == "2026-02-01"
    assert result.config.lifecycle_events[1].date.isoformat() == "2026-02-15"


def test_validate_scenarios_config_reports_asset_swap_missing_source(
    tmp_path: Path,
) -> None:
    """Asset swaps without a remove/source asset should produce the existing message."""
    scenarios_file = tmp_path / "scenarios.yaml"
    _write_scenarios(
        scenarios_file,
        """  - name: Missing Source
    date: 2026-02-01
    asset_swap:
      add:
        name: Deposit A
        category: deposit
        value: 1000000
""",
    )

    result = validate_scenarios_config_file(scenarios_file)

    assert result.config.lifecycle_events == []
    assert [(issue.path, issue.message) for issue in result.issues] == [
        ("lifecycle_events[0].asset_swap.remove", "must be a non-empty string")
    ]


def test_field_helpers_live_in_helper_module() -> None:
    """Scalar field helpers should not live in validate.py."""
    validate_text = (FORECAST_VALIDATORS_DIR / "validate.py").read_text(encoding="utf-8")
    fields_text = (FORECAST_VALIDATORS_DIR / "fields.py").read_text(encoding="utf-8")

    assert "def validate_scenarios_config_file" in validate_text
    assert "def _validate_lifecycle_event" in validate_text
    assert "def _require_string(" not in validate_text
    assert "def _add_issue(" not in validate_text
    assert "def _build_path_locations(" not in validate_text
    assert "def _is_number(" not in validate_text
    assert "def _require_string(" in fields_text
    assert "def _add_issue(" in fields_text
    assert "def _build_path_locations(" in fields_text
    assert "def _is_number(" in fields_text


def test_field_helpers_reexport_from_validate() -> None:
    """Existing validate.py imports should keep resolving to the field helpers."""
    assert _add_issue is fields_add_issue
    assert _build_path_locations is fields_build_path_locations
    assert _require_string is fields_require_string

