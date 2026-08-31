"""Field-level helpers for scenarios.yaml validation.

Owns scalar field checks, YAML location walking, and issue construction.
Section validators stay in ``validate.py``, which re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, TypeGuard, cast

from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from finjuice.pipeline.forecast_validators.models import (
    ScenariosConfigIssue,
    ScenarioValidationIssues,
)


@dataclass(frozen=True)
class _ScenarioIssueContext:
    """Mutable issue sink plus immutable YAML location lookup."""

    locations: dict[str, tuple[int, int]]
    issues: ScenarioValidationIssues

    def add(self, path: str, message: str) -> None:
        """Append one validation issue."""
        _add_issue(self.issues, self.locations, path, message)


def _build_path_locations(node: Node | None) -> dict[str, tuple[int, int]]:
    """Return YAML path -> (line, column) lookups from a composed document."""
    locations: dict[str, tuple[int, int]] = {}
    if node is None:
        return locations
    _walk_node(node, "", locations)
    return locations


def _walk_node(node: Node, path: str, locations: dict[str, tuple[int, int]]) -> None:
    """Populate YAML node locations recursively."""
    locations[path or "$"] = (node.start_mark.line + 1, node.start_mark.column + 1)

    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            key = str(key_node.value)
            child_path = f"{path}.{key}" if path else key
            locations[child_path] = (key_node.start_mark.line + 1, key_node.start_mark.column + 1)
            _walk_node(value_node, child_path, locations)
        return

    if isinstance(node, SequenceNode):
        for index, item_node in enumerate(node.value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            locations[child_path] = (item_node.start_mark.line + 1, item_node.start_mark.column + 1)
            _walk_node(item_node, child_path, locations)


def _require_string(
    payload: dict[str, Any],
    path: str,
    key: str,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> str | None:
    """Require a non-empty string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        _add_issue(issues, locations, f"{path}.{key}", "must be a non-empty string")
        return None
    return value.strip()


def _require_int(
    payload: dict[str, Any],
    path: str,
    key: str,
    context: _ScenarioIssueContext,
    *,
    allow_negative: bool = False,
) -> int | None:
    """Require an integer field, optionally allowing negative values."""
    value = payload.get(key)
    if not _is_int(value) or (not allow_negative and int(cast(int, value)) < 0):
        message = "must be an integer" if allow_negative else "must be a non-negative integer"
        context.add(f"{path}.{key}", message)
        return None
    return int(value)


def _require_number(
    payload: dict[str, Any],
    path: str,
    key: str,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> float | None:
    """Require a numeric field."""
    value = payload.get(key)
    if not _is_number(value):
        _add_issue(issues, locations, f"{path}.{key}", "must be a number")
        return None
    return float(cast(int | float, value))


def _require_date(
    payload: dict[str, Any],
    path: str,
    key: str,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> date | None:
    """Require an ISO-8601 date field."""
    raw_value = payload.get(key)
    if type(raw_value) is date:
        return raw_value
    if not isinstance(raw_value, str):
        _add_issue(issues, locations, f"{path}.{key}", "must be YYYY-MM-DD")
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        _add_issue(issues, locations, f"{path}.{key}", "must be YYYY-MM-DD")
        return None


def _optional_date(
    payload: dict[str, Any],
    path: str,
    key: str,
    locations: dict[str, tuple[int, int]],
    issues: ScenarioValidationIssues,
) -> date | None:
    """Return an optional ISO-8601 date field."""
    if key not in payload or payload.get(key) is None:
        return None
    return _require_date(payload, path, key, locations, issues)


def _add_issue(
    issues: ScenarioValidationIssues,
    locations: dict[str, tuple[int, int]],
    path: str,
    message: str,
) -> None:
    """Append one validation issue with best-effort location metadata."""
    line, column = locations.get(path, locations.get(path.rsplit(".", 1)[0], (None, None)))
    issues.append(ScenariosConfigIssue(path=path, message=message, line=line, column=column))


def _is_non_negative_int(value: Any) -> TypeGuard[int]:
    """Return True when a value is a non-negative integer (but not bool)."""
    return type(value) is int and value >= 0


def _is_int(value: Any) -> TypeGuard[int]:
    """Return True when a value is an integer (but not bool)."""
    return type(value) is int


def _is_number(value: Any) -> TypeGuard[float]:
    """Return True when a value is an int/float but not bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
