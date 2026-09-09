"""Pattern-overlap conflict check for loaded tagging rules.

Owns :func:`check_pattern_overlaps`. The orchestrator
:func:`~finjuice.pipeline.tagging.validator_conflicts.validate_rules` stays in
:mod:`finjuice.pipeline.tagging.validator_conflicts` and re-exports this
check so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import List

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator_conflicts import (
    ValidationIssue,
    _get_patterns,
    _patterns_overlap,
)


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
