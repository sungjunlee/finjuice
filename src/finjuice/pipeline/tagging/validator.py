"""
Rule validation for tagging rules.

Two validation layers live here:

* **Schema validation** — :func:`_validate_rule` orchestrates raw YAML
  mappings into validated rule dicts, raising :class:`ValueError` on malformed
  input. Field and condition helpers live in
  :mod:`finjuice.pipeline.tagging.validator_schema` and are re-exported here
  so existing callers can keep importing from this module. These feed the YAML
  loaders in :mod:`finjuice.pipeline.tagging.rules_yaml_io`.
* **Conflict detection** — :func:`validate_rules` inspects already-loaded
  :class:`~finjuice.pipeline.tagging.models.TagRule` objects for pattern
  overlaps, priority inversions, duplicate names, and regex issues.

Diagnostic labels, Did-you-mean hints, and suggestion-message helpers live in
:mod:`finjuice.pipeline.tagging.validator_format` and are re-exported here so
existing callers can keep importing from this module.

Conflict-detection result types, pattern-overlap helpers, and the per-check
functions live in :mod:`finjuice.pipeline.tagging.validator_conflicts` and are
re-exported here so existing callers can keep importing from this module.
"""

import logging
from typing import Any, Dict, List

from finjuice.pipeline.constants import (
    DEFAULT_RULE_CONFIDENCE,
    DEFAULT_RULE_PRIORITY,
    MAX_RULE_PRIORITY,
    MIN_RULE_PRIORITY,
)
from finjuice.pipeline.tagging.models import (
    REQUIRED_RULE_FIELDS,
    VALID_RULE_FIELDS,
    TagRule,
)
from finjuice.pipeline.tagging.validator_conflicts import (
    ValidationIssue,  # noqa: F401 — re-exported for CLI/test callers.
    ValidationResult,
    _get_patterns,  # noqa: F401 — re-exported for existing validator imports.
    _is_broader_pattern,  # noqa: F401 — re-exported for existing validator imports.
    _patterns_overlap,  # noqa: F401 — re-exported for existing validator imports.
    check_duplicate_names,
    check_pattern_overlaps,
    check_priority_inversions,
    check_regex_validity,
)
from finjuice.pipeline.tagging.validator_format import (
    _append_suggestion,  # noqa: F401 — re-exported for rules_yaml_io callers.
    _candidate_rule_name,
    _extract_suggestion,  # noqa: F401 — re-exported for rules_yaml_io callers.
    _format_rule_label,
)
from finjuice.pipeline.tagging.validator_schema import (
    _parse_between_range,  # noqa: F401 — re-exported for matcher callers.
    _validate_condition,  # noqa: F401 — re-exported for tests.
    _validate_conditions,
    _validate_logic,
    _validate_match_fields,
    _validate_required_string,
    _validate_string_list,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema validation — raw YAML mapping -> validated rule dict
# ---------------------------------------------------------------------------


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
