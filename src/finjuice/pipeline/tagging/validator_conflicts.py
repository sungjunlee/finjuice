"""Conflict detection for loaded tagging rules.

Owns the :func:`validate_rules` orchestrator that inspects already-loaded
:class:`~finjuice.pipeline.tagging.models.TagRule` objects. Individual checks
live in sibling modules and are re-exported here so existing callers can keep
importing from this module:

* :mod:`finjuice.pipeline.tagging.validator_conflicts_duplicates`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_overlaps`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_inversions`
* :mod:`finjuice.pipeline.tagging.validator_conflicts_regex`

Shared dataclasses and pattern helpers live in
:mod:`finjuice.pipeline.tagging.validator_conflicts_types` so siblings never
import this module.

The per-rule schema orchestrator :func:`_validate_rule` stays in
:mod:`finjuice.pipeline.tagging.validator`, which re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

from typing import List

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator_conflicts_duplicates import (
    check_duplicate_names as check_duplicate_names,
)
from finjuice.pipeline.tagging.validator_conflicts_inversions import (
    check_priority_inversions as check_priority_inversions,
)
from finjuice.pipeline.tagging.validator_conflicts_overlaps import (
    check_pattern_overlaps as check_pattern_overlaps,
)
from finjuice.pipeline.tagging.validator_conflicts_regex import (
    check_regex_validity as check_regex_validity,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    ValidationIssue as ValidationIssue,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    ValidationResult as ValidationResult,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    _get_patterns as _get_patterns,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    _is_broader_pattern as _is_broader_pattern,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    _patterns_overlap as _patterns_overlap,
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
