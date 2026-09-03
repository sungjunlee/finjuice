"""Focused validators for scenarios.yaml.

Typed contracts and error types live in ``models.py`` and are re-exported
from this package. Field-level helpers live in ``fields.py`` and are
re-exported from this module. Lifecycle-event helpers live in ``lifecycle.py``
and are re-exported the same way. Assumptions-section helpers live in
``assumptions.py`` and are re-exported the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from finjuice.pipeline.asset_config import (
    ManualAsset,  # noqa: F401 — re-exported for existing validate.py imports
)
from finjuice.pipeline.forecast_validators.assumptions import (
    _SCENARIO_ASSUMPTION_KEYS,  # noqa: F401 — re-exported for existing validate.py imports
    _SCENARIO_NAME_SET,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_asset_returns,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_assumptions,
)
from finjuice.pipeline.forecast_validators.fields import (
    _add_issue,
    _build_path_locations,
    _is_int,  # noqa: F401 — re-exported for existing validate.py imports
    _is_non_negative_int,  # noqa: F401 — re-exported for existing validate.py imports
    _is_number,  # noqa: F401 — re-exported for existing validate.py imports
    _optional_date,  # noqa: F401 — re-exported for existing validate.py imports
    _require_date,  # noqa: F401 — re-exported for existing validate.py imports
    _require_int,  # noqa: F401 — re-exported for existing validate.py imports
    _require_number,  # noqa: F401 — re-exported for existing validate.py imports
    _require_string,  # noqa: F401 — re-exported for existing validate.py imports
    _ScenarioIssueContext,  # noqa: F401 — re-exported for existing validate.py imports
    _walk_node,  # noqa: F401 — re-exported for existing validate.py imports
)
from finjuice.pipeline.forecast_validators.lifecycle import (
    _ASSET_SWAP_ADD_KEYS,  # noqa: F401 — re-exported for existing validate.py imports
    _ASSET_SWAP_KEYS,  # noqa: F401 — re-exported for existing validate.py imports
    _select_lifecycle_event_shape,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_asset_swap,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_asset_swap_event,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_lifecycle_event,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_lifecycle_events,
    _validate_monthly_net_expense_event,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_one_time_expense_event,  # noqa: F401 — re-exported for existing validate.py imports
)
from finjuice.pipeline.forecast_validators.models import (
    SCENARIO_NAMES,  # noqa: F401 — re-exported for existing validate.py imports
    SCENARIOS_CONFIG_VERSION,
    AssetSwapEvent,  # noqa: F401 — re-exported for existing validate.py imports
    LifecycleEvent,  # noqa: F401 — re-exported for existing validate.py imports
    MonthlyNetExpenseEvent,  # noqa: F401 — re-exported for existing validate.py imports
    OneTimeExpenseEvent,  # noqa: F401 — re-exported for existing validate.py imports
    ScenarioAssumptions,  # noqa: F401 — re-exported for existing validate.py imports
    ScenariosConfig,
    ScenariosConfigIssue,
    ScenariosConfigValidationResult,
    ScenarioValidationIssues,
)

_SCENARIO_TOP_LEVEL_KEYS = {"version", "assumptions", "lifecycle_events"}


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
