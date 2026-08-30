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
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

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
