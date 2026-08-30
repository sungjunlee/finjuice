"""Conflict-detection helpers for tagging rule validation.

Owns result types, pattern-overlap analysis, and the per-check functions used
by :func:`validate_rules`. Schema field helpers live in
:mod:`finjuice.pipeline.tagging.validator_schema`. Diagnostic labels live in
:mod:`finjuice.pipeline.tagging.validator_format`. The per-rule orchestrator
:func:`_validate_rule` and the conflict-detection orchestrator
:func:`validate_rules` stay in :mod:`finjuice.pipeline.tagging.validator`,
which re-exports the names that existing callers import from that module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from finjuice.pipeline.tagging.models import TagRule


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
