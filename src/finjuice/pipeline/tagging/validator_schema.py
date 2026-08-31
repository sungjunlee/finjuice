"""Schema field and condition helpers for tagging rule validation.

Owns required-string/list checks, match/fields pairing, condition parsing
(including numeric ``between`` ranges), and logic-mode validation. The
per-rule orchestrator :func:`_validate_rule` stays in
:mod:`finjuice.pipeline.tagging.validator` and conflict detection lives in
:mod:`finjuice.pipeline.tagging.validator_conflicts`; both re-export the
names that existing callers import from the validator module.
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

from finjuice.pipeline.tagging.models import (
    NUMERIC_CONDITION_OPERATORS,
    VALID_CONDITION_LOGIC,
    VALID_CONDITION_OPERATORS,
    Condition,
    _RuleValidationHintError,
)
from finjuice.pipeline.tagging.validator_format import (
    _format_condition_context,
    _format_did_you_mean,
    _format_rule_label,
)


def _validate_required_string(value: Any, rule_label: str, field_name: str) -> str:
    """Validate a required non-empty string field."""
    if not isinstance(value, str):
        raise ValueError(
            f"{rule_label}: '{field_name}' must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ValueError(f"{rule_label}: '{field_name}' cannot be empty or whitespace-only")
    return value


def _validate_string_list(value: Any, rule_label: str, field_name: str) -> List[str]:
    """Validate a required non-empty list of non-empty strings."""
    if not isinstance(value, list):
        raise ValueError(f"{rule_label}: '{field_name}' must be a list, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{rule_label}: '{field_name}' cannot be empty")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{rule_label}: all items in '{field_name}' must be strings")
    if not all(item.strip() for item in value):
        raise ValueError(
            f"{rule_label}: '{field_name}' cannot contain empty or whitespace-only strings"
        )
    return cast(list[Any], value)


def _validate_match_fields(rule_dict: Dict[str, Any], rule_label: str) -> tuple[str, List[str]]:
    """Validate legacy match/fields config when present."""
    has_match = "match" in rule_dict
    has_fields = "fields" in rule_dict
    if has_match != has_fields:
        missing = ["match"] if not has_match else ["fields"]
        raise ValueError(f"{rule_label} missing required fields: {missing}")
    if not has_match:
        return "", []
    match = _validate_required_string(rule_dict["match"], rule_label, "match")
    fields = _validate_string_list(rule_dict["fields"], rule_label, "fields")
    return match, fields


def _parse_between_range(value: str) -> tuple[float | None, float | None]:
    """Parse a ``min,max`` numeric range from a normalized condition string.

    Shared by numeric-condition schema validation and the matching engine in
    :mod:`finjuice.pipeline.tagging.rules`.
    """
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None, None


def _validate_condition(
    rule_name: str,
    condition_dict: Any,
    index: int,
    *,
    rule_index: int | None = None,
) -> Condition:
    """Validate a single condition mapping."""
    rule_label = _format_rule_label(rule_name, rule_index)
    condition_context = _format_condition_context(rule_name, index, rule_index=rule_index)
    if not isinstance(condition_dict, dict):
        raise ValueError(
            f"{condition_context} must be a dictionary, got {type(condition_dict).__name__}"
        )
    missing = {"field", "op", "value"} - set(condition_dict.keys())
    if missing:
        raise ValueError(f"{condition_context} missing required fields: {sorted(missing)}")
    fld = _validate_required_string(condition_dict["field"], rule_label, "field")
    op = _validate_required_string(condition_dict["op"], rule_label, "op")
    raw_val = condition_dict["value"]
    if op == "between" and isinstance(raw_val, (list, tuple)):
        if len(raw_val) != 2:
            raise ValueError(
                f"{condition_context} 'between' value must have exactly 2 elements, "
                f"got {len(raw_val)}. "
                "Use [min, max] list or 'min,max' string."
            )
        raw_val = f"{raw_val[0]},{raw_val[1]}"
    # Coerce YAML-parsed int/float to str for numeric operators
    if isinstance(raw_val, (int, float)):
        raw_val = str(raw_val)
    val = _validate_required_string(raw_val, rule_label, "value")
    if op not in VALID_CONDITION_OPERATORS:
        allowed = sorted(VALID_CONDITION_OPERATORS)
        suggestion = _format_did_you_mean(op, VALID_CONDITION_OPERATORS)
        raise _RuleValidationHintError(
            f"{condition_context} has invalid operator '{op}'. Allowed: {allowed}.",
            suggestion=suggestion,
        )
    if op in NUMERIC_CONDITION_OPERATORS:
        _validate_numeric_condition_value(condition_context, op, val)
    return Condition(field=fld, op=op, value=val)


def _validate_numeric_condition_value(ctx: str, op: str, value: str) -> None:
    """Validate numeric condition values encoded as YAML strings."""
    if op == "between":
        minimum, maximum = _parse_between_range(value)
        if minimum is None or maximum is None:
            raise ValueError(
                f"{ctx} has invalid 'value' for between: {value!r}. "
                "Use [min, max] list or 'min,max' string "
                "(e.g., [-50000, -10000] or '-50000,-10000')."
            )
        if minimum > maximum:
            raise ValueError(f"{ctx} has invalid 'value' for between: min must be <= max")
        return
    try:
        float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx} has invalid numeric 'value': {value!r}") from exc


def _validate_conditions(
    rule_dict: Dict[str, Any],
    rule_name: str,
    *,
    rule_index: int | None = None,
) -> List[Condition]:
    """Validate conditions list when present."""
    if "conditions" not in rule_dict:
        return []

    conditions = rule_dict["conditions"]
    if not isinstance(conditions, list):
        raise ValueError(
            f"{_format_rule_label(rule_name, rule_index)}: "
            f"'conditions' must be a list, got {type(conditions).__name__}"
        )
    if not conditions:
        raise ValueError(
            f"{_format_rule_label(rule_name, rule_index)}: 'conditions' cannot be empty"
        )
    return [
        _validate_condition(rule_name, condition_dict, idx, rule_index=rule_index)
        for idx, condition_dict in enumerate(conditions)
    ]


def _validate_logic(
    rule_dict: Dict[str, Any],
    rule_name: str,
    *,
    rule_index: int | None = None,
) -> str:
    """Validate conditions logic mode."""
    logic = rule_dict.get("logic", "all")
    if not isinstance(logic, str) or logic not in VALID_CONDITION_LOGIC:
        raise ValueError(
            f"{_format_rule_label(rule_name, rule_index)}: "
            f"'logic' must be one of {sorted(VALID_CONDITION_LOGIC)}, "
            f"got {logic!r}"
        )
    return logic
