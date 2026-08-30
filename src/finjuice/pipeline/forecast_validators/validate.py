"""Focused validators for scenarios.yaml.

Typed contracts and error types live in ``models.py`` and are re-exported
from this package. Field-level helpers live in ``fields.py`` and are
re-exported from this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from finjuice.pipeline.asset_config import ASSET_CATEGORIES, ManualAsset
from finjuice.pipeline.forecast_validators.fields import (
    _add_issue,
    _build_path_locations,
    _is_int,  # noqa: F401 — re-exported for existing validate.py imports
    _is_non_negative_int,
    _is_number,
    _optional_date,
    _require_date,
    _require_int,
    _require_number,
    _require_string,
    _ScenarioIssueContext,
    _walk_node,  # noqa: F401 — re-exported for existing validate.py imports
)
from finjuice.pipeline.forecast_validators.models import (
    SCENARIO_NAMES,
    SCENARIOS_CONFIG_VERSION,
    AssetSwapEvent,
    LifecycleEvent,
    MonthlyNetExpenseEvent,
    OneTimeExpenseEvent,
    ScenarioAssumptions,
    ScenariosConfig,
    ScenariosConfigIssue,
    ScenariosConfigValidationResult,
    ScenarioValidationIssues,
)

_SCENARIO_NAME_SET = set(SCENARIO_NAMES)
_SCENARIO_TOP_LEVEL_KEYS = {"version", "assumptions", "lifecycle_events"}
_SCENARIO_ASSUMPTION_KEYS = {"default_savings_per_month", "asset_returns", "liability_rate_delta"}
_ASSET_SWAP_KEYS = {"remove", "add"}
_ASSET_SWAP_ADD_KEYS = {"name", "category", "value"}


def validate_scenarios_config_file(
    scenarios_file: Path,
    *,
    allow_missing_file: bool = False,
) -> ScenariosConfigValidationResult:
    """Validate scenarios.yaml and return structured issues."""
    if not scenarios_file.exists():
        return ScenariosConfigValidationResult(
            path=scenarios_file,
            exists=False,
            config=ScenariosConfig(),
            issues=(
                []
                if allow_missing_file
                else [ScenariosConfigIssue(path="scenarios.yaml", message="file not found")]
            ),
        )

    raw_text = scenarios_file.read_text(encoding="utf-8")
    try:
        document = yaml.compose(raw_text)
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        issue = ScenariosConfigIssue(
            path="scenarios.yaml",
            message="invalid YAML syntax",
            line=(mark.line + 1) if mark is not None else None,
            column=(mark.column + 1) if mark is not None else None,
        )
        return ScenariosConfigValidationResult(
            path=scenarios_file,
            exists=True,
            config=ScenariosConfig(),
            issues=[issue],
        )

    if payload is None:
        payload = {}

    locations = _build_path_locations(document)
    issues: ScenarioValidationIssues = []
    config = _validate_scenarios_payload(payload, locations, issues)

    return ScenariosConfigValidationResult(
        path=scenarios_file,
        exists=True,
        config=config,
        issues=issues,
    )


def _validate_scenarios_payload(
    payload: Any,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> ScenariosConfig:
    """Validate the parsed scenarios.yaml payload."""
    if not isinstance(payload, dict):
        _add_issue(issues, locations, "scenarios.yaml", "top-level document must be a mapping")
        return ScenariosConfig()

    unknown_top_level = sorted(set(payload) - _SCENARIO_TOP_LEVEL_KEYS)
    for key in unknown_top_level:
        _add_issue(issues, locations, key, "unknown top-level field")

    version = payload.get("version")
    if version != SCENARIOS_CONFIG_VERSION:
        _add_issue(issues, locations, "version", f"must be {SCENARIOS_CONFIG_VERSION}")

    assumptions_payload = payload.get("assumptions")
    assumptions = _validate_assumptions(assumptions_payload, locations, issues)
    lifecycle_events = _validate_lifecycle_events(
        payload.get("lifecycle_events", []),
        locations,
        issues,
    )

    if issues:
        return ScenariosConfig()

    return ScenariosConfig(
        version=SCENARIOS_CONFIG_VERSION,
        assumptions=assumptions,
        lifecycle_events=lifecycle_events,
    )


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


def _validate_lifecycle_events(
    value: Any,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> list[LifecycleEvent]:
    """Validate lifecycle_events."""
    if value is None:
        return []
    if not isinstance(value, list):
        _add_issue(issues, locations, "lifecycle_events", "must be a list")
        return []

    context = _ScenarioIssueContext(locations=locations, issues=issues)
    validated: list[LifecycleEvent] = []
    for index, item in enumerate(value):
        path = f"lifecycle_events[{index}]"
        event = _validate_lifecycle_event(item, path, context)
        if event is not None:
            validated.append(event)

    return validated


def _validate_lifecycle_event(
    item: Any,
    path: str,
    context: _ScenarioIssueContext,
) -> LifecycleEvent | None:
    """Validate one lifecycle event."""
    if not isinstance(item, dict):
        context.add(path, "must be a mapping")
        return None

    name = _require_string(item, path, "name", context.locations, context.issues)
    if name is None:
        return None

    event_shape = _select_lifecycle_event_shape(item, path, context)
    if event_shape == "one_time_expense":
        return _validate_one_time_expense_event(item, path, name, context)
    if event_shape == "monthly_net_expense":
        return _validate_monthly_net_expense_event(item, path, name, context)
    if event_shape == "asset_swap":
        return _validate_asset_swap_event(item, path, name, context)
    return None


def _select_lifecycle_event_shape(
    item: dict[str, Any],
    path: str,
    context: _ScenarioIssueContext,
) -> str | None:
    """Return the single declared lifecycle event shape."""
    event_shapes = [
        field
        for field in ("one_time_expense", "monthly_net_expense", "asset_swap")
        if field in item
    ]
    if len(event_shapes) == 1:
        return event_shapes[0]

    message = (
        "must declare one of: one_time_expense, monthly_net_expense, asset_swap"
        if not event_shapes
        else "must declare exactly one of: one_time_expense, monthly_net_expense, asset_swap"
    )
    context.add(path, message)
    return None


def _validate_one_time_expense_event(
    item: dict[str, Any],
    path: str,
    name: str,
    context: _ScenarioIssueContext,
) -> OneTimeExpenseEvent | None:
    """Validate a one-time expense lifecycle event."""
    event_date = _require_date(item, path, "date", context.locations, context.issues)
    amount = _require_int(item, path, "one_time_expense", context, allow_negative=True)
    if event_date is None or amount is None:
        return None
    return OneTimeExpenseEvent(name=name, date=event_date, one_time_expense=amount)


def _validate_monthly_net_expense_event(
    item: dict[str, Any],
    path: str,
    name: str,
    context: _ScenarioIssueContext,
) -> MonthlyNetExpenseEvent | None:
    """Validate a monthly net expense lifecycle event."""
    start_date = _require_date(item, path, "start", context.locations, context.issues)
    end_date = _optional_date(item, path, "end", context.locations, context.issues)
    amount = _require_int(item, path, "monthly_net_expense", context, allow_negative=True)
    if start_date is None or amount is None:
        return None
    if end_date is not None and end_date < start_date:
        context.add(f"{path}.end", "must be on or after start")
        return None
    return MonthlyNetExpenseEvent(
        name=name,
        start=start_date,
        end=end_date,
        monthly_net_expense=amount,
    )


def _validate_asset_swap_event(
    item: dict[str, Any],
    path: str,
    name: str,
    context: _ScenarioIssueContext,
) -> AssetSwapEvent | None:
    """Validate an asset swap lifecycle event."""
    event_date = _require_date(item, path, "date", context.locations, context.issues)
    asset_swap = _validate_asset_swap(
        item.get("asset_swap"),
        path,
        context.locations,
        context.issues,
    )
    if event_date is None or asset_swap is None:
        return None
    return AssetSwapEvent(
        name=name,
        date=event_date,
        remove=asset_swap["remove"],
        add=asset_swap["add"],
    )


def _validate_asset_swap(
    value: Any,
    path: str,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> dict[str, Any] | None:
    """Validate one asset_swap payload."""
    if not isinstance(value, dict):
        _add_issue(issues, locations, f"{path}.asset_swap", "must be a mapping")
        return None

    unknown_keys = sorted(set(value) - _ASSET_SWAP_KEYS)
    for key in unknown_keys:
        _add_issue(issues, locations, f"{path}.asset_swap.{key}", "unknown field")

    remove = _require_string(value, f"{path}.asset_swap", "remove", locations, issues)
    add_payload = value.get("add")
    if not isinstance(add_payload, dict):
        _add_issue(issues, locations, f"{path}.asset_swap.add", "must be a mapping")
        return None

    unknown_add_keys = sorted(set(add_payload) - _ASSET_SWAP_ADD_KEYS)
    for key in unknown_add_keys:
        _add_issue(issues, locations, f"{path}.asset_swap.add.{key}", "unknown field")

    add_name = _require_string(add_payload, f"{path}.asset_swap.add", "name", locations, issues)
    add_category = _require_string(
        add_payload,
        f"{path}.asset_swap.add",
        "category",
        locations,
        issues,
    )
    add_value = _require_number(
        add_payload,
        f"{path}.asset_swap.add",
        "value",
        locations,
        issues,
    )

    if add_category is not None and add_category not in ASSET_CATEGORIES:
        allowed = ", ".join(ASSET_CATEGORIES)
        _add_issue(
            issues,
            locations,
            f"{path}.asset_swap.add.category",
            f"must be one of: {allowed}",
        )

    if remove is None or add_name is None or add_category is None or add_value is None:
        return None

    return {
        "remove": remove,
        "add": ManualAsset(name=add_name, category=add_category, value=float(add_value)),
    }
