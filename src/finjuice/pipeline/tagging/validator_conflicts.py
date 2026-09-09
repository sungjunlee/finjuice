"""Conflict detection for loaded tagging rules.

Owns the :class:`ValidationIssue`/:class:`ValidationResult` dataclasses and
the :func:`validate_rules` orchestrator that inspects already-loaded
:class:`~finjuice.pipeline.tagging.models.TagRule` objects. Individual checks
live in sibling modules and are re-exported here so existing callers can keep
importing from this module:

* :mod:`finjuice.pipeline.tagging.validator_conflicts_duplicates`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_overlaps`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_inversions`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_regex`

The per-rule schema orchestrator :func:`_validate_rule` stays in
:mod:`finjuice.pipeline.tagging.validator`, which re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

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


from finjuice.pipeline.tagging.validator_conflicts_duplicates import (  # noqa: E402, I001
    check_duplicate_names as check_duplicate_names,
)
from finjuice.pipeline.tagging.validator_conflicts_inversions import (  # noqa: E402, I001
    check_priority_inversions as check_priority_inversions,
)
from finjuice.pipeline.tagging.validator_conflicts_overlaps import (  # noqa: E402, I001
    check_pattern_overlaps as check_pattern_overlaps,
)
from finjuice.pipeline.tagging.validator_conflicts_regex import (  # noqa: E402, I001
    check_regex_validity as check_regex_validity,
)


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
