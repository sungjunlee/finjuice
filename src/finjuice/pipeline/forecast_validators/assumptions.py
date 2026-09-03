"""Assumptions-section validators for scenarios.yaml.

Owns ``assumptions`` mapping/shape checks plus nested ``asset_returns``.
Field-level helpers stay in ``fields.py``. Payload orchestration stays in
``validate.py``, which re-exports these names so existing callers can keep
importing from that module.
"""

from __future__ import annotations

from typing import Any, cast

from finjuice.pipeline.asset_config import ASSET_CATEGORIES
from finjuice.pipeline.forecast_validators.fields import (
    _add_issue,
    _is_non_negative_int,
    _is_number,
)
from finjuice.pipeline.forecast_validators.models import (
    SCENARIO_NAMES,
    ScenarioAssumptions,
    ScenarioValidationIssues,
)

_SCENARIO_NAME_SET = set(SCENARIO_NAMES)
_SCENARIO_ASSUMPTION_KEYS = {"default_savings_per_month", "asset_returns", "liability_rate_delta"}


def _validate_assumptions(
    value: Any,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> ScenarioAssumptions:
    """Validate the assumptions block."""
    if not isinstance(value, dict):
        _add_issue(issues, locations, "assumptions", "must be a mapping")
        return ScenarioAssumptions()

    unknown_keys = sorted(set(value) - _SCENARIO_ASSUMPTION_KEYS)
    for key in unknown_keys:
        _add_issue(issues, locations, f"assumptions.{key}", "unknown field")

    savings_raw = value.get("default_savings_per_month")
    if not _is_non_negative_int(savings_raw):
        _add_issue(
            issues,
            locations,
            "assumptions.default_savings_per_month",
            "must be a non-negative integer",
        )
        savings = 0
    else:
        savings = int(savings_raw)

    asset_returns = _validate_asset_returns(value.get("asset_returns"), locations, issues)

    liability_rate_delta_raw = value.get("liability_rate_delta", 0.0)
    if not _is_number(liability_rate_delta_raw):
        _add_issue(
            issues,
            locations,
            "assumptions.liability_rate_delta",
            "must be a number",
        )
        liability_rate_delta = 0.0
    else:
        liability_rate_delta = float(liability_rate_delta_raw)

    return ScenarioAssumptions(
        default_savings_per_month=savings,
        asset_returns=asset_returns,
        liability_rate_delta=liability_rate_delta,
    )


def _validate_asset_returns(
    value: Any,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> dict[str, dict[str, float]]:
    """Validate assumptions.asset_returns."""
    if not isinstance(value, dict):
        _add_issue(issues, locations, "assumptions.asset_returns", "must be a mapping")
        return {}

    asset_returns: dict[str, dict[str, float]] = {}
    for category, scenario_map in value.items():
        category_path = f"assumptions.asset_returns.{category}"
        if category not in ASSET_CATEGORIES:
            allowed = ", ".join(ASSET_CATEGORIES)
            _add_issue(issues, locations, category_path, f"must be one of: {allowed}")
            continue
        if not isinstance(scenario_map, dict):
            _add_issue(issues, locations, category_path, "must be a mapping")
            continue

        unknown_scenarios = sorted(set(scenario_map) - _SCENARIO_NAME_SET)
        for scenario_name in unknown_scenarios:
            _add_issue(
                issues,
                locations,
                f"{category_path}.{scenario_name}",
                "unknown field",
            )

        scenario_rates: dict[str, float] = {}
        for scenario_name in SCENARIO_NAMES:
            raw_rate = scenario_map.get(scenario_name)
            path = f"{category_path}.{scenario_name}"
            if not _is_number(raw_rate):
                _add_issue(issues, locations, path, "must be a number")
                continue
            scenario_rates[scenario_name] = float(cast(int | float, raw_rate))
        if len(scenario_rates) == len(SCENARIO_NAMES):
            asset_returns[category] = scenario_rates
    return asset_returns
