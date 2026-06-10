"""
Rule validation for tagging rules.

Two validation layers live here:

* **Schema validation** — :func:`_validate_rule` and friends turn raw YAML
  mappings into validated rule dicts, raising :class:`ValueError` on malformed
  input. These feed the YAML loaders in
  :mod:`finjuice.pipeline.tagging.rules_yaml_io`.
* **Conflict detection** — :func:`validate_rules` inspects already-loaded
  :class:`~finjuice.pipeline.tagging.models.TagRule` objects for pattern
  overlaps, priority inversions, duplicate names, and regex issues.
"""

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Final, List, Optional, Set, Tuple, cast

from finjuice.pipeline.constants import (
    DEFAULT_RULE_CONFIDENCE,
    DEFAULT_RULE_PRIORITY,
    MAX_RULE_PRIORITY,
    MIN_RULE_PRIORITY,
)
from finjuice.pipeline.tagging.models import (
    NUMERIC_CONDITION_OPERATORS,
    REQUIRED_RULE_FIELDS,
    VALID_CONDITION_LOGIC,
    VALID_CONDITION_OPERATORS,
    VALID_RULE_FIELDS,
    Condition,
    TagRule,
    _RuleValidationHintError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema validation — raw YAML mapping -> validated rule dict
# ---------------------------------------------------------------------------


def _candidate_rule_name(rule_dict: Any, rule_index: int) -> str:
    """Best-effort rule name for diagnostics, even when validation fails."""
    fallback_name = f"UNNAMED_RULE_{rule_index}"
    if not isinstance(rule_dict, dict):
        return fallback_name

    raw_name = rule_dict.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    if raw_name is None:
        return fallback_name
    return str(raw_name)


def _format_rule_label(rule_name: str, rule_index: int | None = None) -> str:
    """Format a rule label for human-readable validation errors."""
    if rule_index is None:
        return f"Rule '{rule_name}'"
    return f"Rule '{rule_name}' (#{rule_index})"


def _format_condition_context(
    rule_name: str,
    condition_index: int,
    *,
    rule_index: int | None = None,
) -> str:
    """Format a condition-specific validation context string."""
    return f"{_format_rule_label(rule_name, rule_index)} condition at index {condition_index}"


# Common alias map for operator typos that difflib's edit-distance misses.
# Keeps the user-facing suggestion reliable for frequent mistakes.
_OPERATOR_ALIASES: Final = {
    "equal": "is",
    "equals": "is",
    "eq": "is",
    "ne": "is_not",
    "notequal": "is_not",
    "lt": "less_than",
    "gt": "greater_than",
    "matches": "regex",
    "startswith": "starts_with",
    "start_with": "starts_with",
    "contain": "contains",
    "has": "contains",
    "in_range": "between",
}


def _format_did_you_mean(value: str, candidates: set[str]) -> str | None:
    """Return a short Did-you-mean hint for a mistyped token.

    Tries an alias map first (catches common substitutions like `equal` -> `is`
    that fall below difflib's similarity threshold), then falls back to
    edit-distance matching against the allowed candidates.
    """
    alias = _OPERATOR_ALIASES.get(value.lower())
    if alias and alias in candidates:
        return f"Did you mean: '{alias}'?"
    matches = difflib.get_close_matches(value, sorted(candidates), n=2, cutoff=0.6)
    if not matches:
        return None
    return f"Did you mean: '{matches[0]}'?"


def _extract_suggestion(exc: ValueError) -> str | None:
    """Extract an optional suggestion from internal validation exceptions."""
    return getattr(exc, "suggestion", None)


def _append_suggestion(message: str, suggestion: str | None) -> str:
    """Append a suggestion to a strict-mode error message when available."""
    if not suggestion:
        return message
    return f"{message}\n{suggestion}"


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


def _validate_rule(rule_dict: Dict[str, Any], rule_index: int) -> Dict[str, Any]:
    """
    Validate a single rule dictionary.

    Args:
        rule_dict: Rule configuration from YAML
        rule_index: Index in rules list (for error messages)

    Returns:
        Validated rule dict with defaults applied

    Raises:
        ValueError: If rule is invalid
    """
    rule_name = _candidate_rule_name(rule_dict, rule_index)
    rule_label = _format_rule_label(rule_name, rule_index)

    if not isinstance(rule_dict, dict):
        raise ValueError(f"{rule_label} must be a dictionary, got {type(rule_dict).__name__}")

    # Check required fields
    missing_fields = REQUIRED_RULE_FIELDS - set(rule_dict.keys())
    if missing_fields:
        raise ValueError(
            f"{rule_label} missing required fields: {sorted(missing_fields)}\n"
            f"Required fields: {sorted(REQUIRED_RULE_FIELDS)}"
        )

    rule_name = _validate_required_string(rule_dict["name"], rule_label, "name")
    rule_label = _format_rule_label(rule_name, rule_index)

    # Warn about unknown fields (but don't fail - allows for extensions)
    unknown_fields = set(rule_dict.keys()) - VALID_RULE_FIELDS
    if unknown_fields:
        logger.warning(
            f"{rule_label} has unknown fields: {sorted(unknown_fields)}. These will be ignored."
        )

    tags = _validate_string_list(rule_dict["tags"], rule_label, "tags")
    match, fields = _validate_match_fields(rule_dict, rule_label)
    conditions = _validate_conditions(rule_dict, rule_name, rule_index=rule_index)
    logic = _validate_logic(rule_dict, rule_name, rule_index=rule_index)

    if not match and not conditions:
        raise ValueError(
            f"{rule_label} must define either 'conditions' or both 'match' and 'fields'"
        )

    validated = {
        "name": rule_name,
        "match": match,
        "fields": fields,
        "tags": tags,
        "conditions": conditions,
        "logic": logic,
        "priority": rule_dict.get("priority", DEFAULT_RULE_PRIORITY),
        "enabled": rule_dict.get("enabled", True),
        "category": rule_dict.get("category", ""),
        "created_by": rule_dict.get("created_by", "manual"),
        "created_at": rule_dict.get("created_at", ""),
        "confidence": rule_dict.get("confidence", DEFAULT_RULE_CONFIDENCE),
        "notes": rule_dict.get("notes", ""),
    }

    # Validate priority range (after applying default)
    priority = validated["priority"]
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(
            f"{rule_label}: 'priority' must be an integer, got {type(priority).__name__}"
        )

    if not MIN_RULE_PRIORITY <= priority <= MAX_RULE_PRIORITY:
        raise ValueError(
            f"{rule_label}: 'priority' must be "
            f"{MIN_RULE_PRIORITY}-{MAX_RULE_PRIORITY}, got {priority}"
        )

    return validated


# ---------------------------------------------------------------------------
# Conflict detection — inspect loaded rules for overlaps and inversions
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    """Single validation issue found in rules."""

    severity: str  # "error", "warning", "info"
    issue_type: str  # "duplicate_name", "pattern_overlap", "priority_inversion"
    message: str
    rules_involved: List[str] = field(default_factory=list)  # Rule names
    suggestion: Optional[str] = None
    rule_index: Optional[int] = None
    rule_name: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of rule validation."""

    total_rules: int
    issues: List[ValidationIssue] = field(default_factory=list)
    passed: int = 0

    @property
    def errors(self) -> List[ValidationIssue]:
        """Get only error-level issues."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Get only warning-level issues."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return len(self.warnings) > 0


def _get_patterns(rule: TagRule) -> Set[str]:
    """Extract individual patterns from rule's match string."""
    return {p.strip().lower() for p in rule.match.split("|") if p.strip()}


def _patterns_overlap(patterns1: Set[str], patterns2: Set[str]) -> Tuple[bool, Set[str]]:
    """
    Check if two pattern sets have any overlap.

    Returns:
        Tuple of (has_overlap, overlapping_patterns)
    """
    # Direct overlap: same patterns
    direct_overlap = patterns1 & patterns2
    if direct_overlap:
        return True, direct_overlap

    # Substring overlap: one pattern contains another
    substring_overlaps = set()
    for p1 in patterns1:
        for p2 in patterns2:
            if p1 in p2 or p2 in p1:
                substring_overlaps.add(f"{p1}⊂{p2}" if p1 in p2 else f"{p2}⊂{p1}")

    if substring_overlaps:
        return True, substring_overlaps

    return False, set()


def _is_broader_pattern(pattern1: str, pattern2: str) -> bool:
    """
    Check if pattern1 is broader (less specific) than pattern2.

    A pattern is broader if it's shorter or is a substring of the other.
    """
    p1_lower = pattern1.lower()
    p2_lower = pattern2.lower()

    # If p1 is contained in p2, p1 is broader
    if p1_lower in p2_lower and p1_lower != p2_lower:
        return True

    return False


def check_duplicate_names(rules: List[TagRule]) -> List[ValidationIssue]:
    """Check for duplicate rule names."""
    issues = []
    seen_names: dict[str, int] = {}

    for rule in rules:
        if rule.name in seen_names:
            issues.append(
                ValidationIssue(
                    severity="error",
                    issue_type="duplicate_name",
                    message=f"Duplicate rule name: '{rule.name}'",
                    rules_involved=[rule.name],
                    suggestion=f"Rename one of the '{rule.name}' rules to be unique",
                )
            )
        else:
            seen_names[rule.name] = 1

    return issues


def check_pattern_overlaps(rules: List[TagRule]) -> List[ValidationIssue]:
    """
    Check for pattern overlaps between rules.

    Two rules overlap if they might match the same transaction.
    """
    issues = []

    for i, rule1 in enumerate(rules):
        patterns1 = _get_patterns(rule1)

        for rule2 in rules[i + 1 :]:
            # Skip if different fields (they won't conflict)
            if set(rule1.fields) != set(rule2.fields):
                continue

            patterns2 = _get_patterns(rule2)
            has_overlap, overlapping = _patterns_overlap(patterns1, patterns2)

            if has_overlap:
                # Determine which rule wins based on priority
                winner = rule1 if rule1.priority >= rule2.priority else rule2

                issues.append(
                    ValidationIssue(
                        severity="warning",
                        issue_type="pattern_overlap",
                        message=(
                            f"Pattern overlap: '{rule1.name}' (pri:{rule1.priority}) "
                            f"and '{rule2.name}' (pri:{rule2.priority}) "
                            f"overlap: {overlapping}"
                        ),
                        rules_involved=[rule1.name, rule2.name],
                        suggestion=(
                            f"'{winner.name}' will match first. "
                            f"Consider merging or adjusting priorities."
                        ),
                    )
                )

    return issues


def check_priority_inversions(rules: List[TagRule]) -> List[ValidationIssue]:
    """
    Check for priority inversions.

    A priority inversion occurs when a broader (less specific) pattern
    has higher priority than a more specific pattern, causing the
    specific pattern to never match.
    """
    issues = []

    for i, rule1 in enumerate(rules):
        patterns1 = _get_patterns(rule1)

        for rule2 in rules[i + 1 :]:
            # Skip if different fields
            if set(rule1.fields) != set(rule2.fields):
                continue

            patterns2 = _get_patterns(rule2)

            # Check if rule1 is broader than rule2
            for p1 in patterns1:
                for p2 in patterns2:
                    if _is_broader_pattern(p1, p2):
                        # rule1 is broader, check if it has higher priority
                        if rule1.priority > rule2.priority:
                            issues.append(
                                ValidationIssue(
                                    severity="warning",
                                    issue_type="priority_inversion",
                                    message=(
                                        f"Priority inversion: '{rule1.name}' (pri:{rule1.priority})"
                                        f" broader '{p1}' vs '{rule2.name}' (pri:{rule2.priority})"
                                        f" specific '{p2}'"
                                    ),
                                    rules_involved=[rule1.name, rule2.name],
                                    suggestion=(
                                        f"'{p2}' won't match. "
                                        f"Raise '{rule2.name}' priority > {rule1.priority}."
                                    ),
                                )
                            )
                    elif _is_broader_pattern(p2, p1):
                        # rule2 is broader, check if it has higher priority
                        if rule2.priority > rule1.priority:
                            issues.append(
                                ValidationIssue(
                                    severity="warning",
                                    issue_type="priority_inversion",
                                    message=(
                                        f"Priority inversion: '{rule2.name}' (pri:{rule2.priority})"
                                        f" broader '{p2}' vs '{rule1.name}' (pri:{rule1.priority})"
                                        f" specific '{p1}'"
                                    ),
                                    rules_involved=[rule2.name, rule1.name],
                                    suggestion=(
                                        f"'{p1}' won't match. "
                                        f"Raise '{rule1.name}' priority > {rule2.priority}."
                                    ),
                                )
                            )

    return issues


def check_regex_validity(rules: List[TagRule]) -> List[ValidationIssue]:
    """Check if match patterns are valid regex (for future regex mode)."""
    issues = []

    for rule in rules:
        patterns = rule.match.split("|")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                issues.append(
                    ValidationIssue(
                        severity="info",
                        issue_type="invalid_regex",
                        message=f"Rule '{rule.name}': pattern '{pattern}' is not valid regex: {e}",
                        rules_involved=[rule.name],
                        suggestion="OK for substring match, won't work in regex mode.",
                    )
                )

    return issues


def validate_rules(rules: List[TagRule]) -> ValidationResult:
    """
    Run all validation checks on rules.

    Args:
        rules: List of TagRule objects

    Returns:
        ValidationResult with all found issues
    """
    result = ValidationResult(total_rules=len(rules))

    # Run all checks
    result.issues.extend(check_duplicate_names(rules))
    result.issues.extend(check_pattern_overlaps(rules))
    result.issues.extend(check_priority_inversions(rules))
    result.issues.extend(check_regex_validity(rules))

    # Calculate passed rules (rules not involved in any error/warning)
    rules_with_issues = set()
    for issue in result.issues:
        if issue.severity in ("error", "warning"):
            rules_with_issues.update(issue.rules_involved)

    result.passed = len(rules) - len(rules_with_issues)

    return result
