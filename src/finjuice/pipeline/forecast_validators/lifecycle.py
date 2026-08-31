"""Lifecycle-event section validators for scenarios.yaml.

Owns ``lifecycle_events`` list/shape checks plus nested one-time, monthly-net,
and asset-swap event shapes. Field-level helpers stay in ``fields.py``. Payload
orchestration stays in ``validate.py``, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.asset_config import ASSET_CATEGORIES, ManualAsset
from finjuice.pipeline.forecast_validators.fields import (
    _add_issue,
    _optional_date,
    _require_date,
    _require_int,
    _require_number,
    _require_string,
    _ScenarioIssueContext,
)
from finjuice.pipeline.forecast_validators.models import (
    AssetSwapEvent,
    LifecycleEvent,
    MonthlyNetExpenseEvent,
    OneTimeExpenseEvent,
    ScenarioValidationIssues,
)

_ASSET_SWAP_KEYS = {"remove", "add"}
_ASSET_SWAP_ADD_KEYS = {"name", "category", "value"}


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
