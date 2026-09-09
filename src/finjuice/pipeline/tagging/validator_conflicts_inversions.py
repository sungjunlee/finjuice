"""Priority-inversion conflict check for loaded tagging rules.

Owns :func:`check_priority_inversions`. The orchestrator
:func:`~finjuice.pipeline.tagging.validator_conflicts.validate_rules` stays in
:mod:`finjuice.pipeline.tagging.validator_conflicts` and re-exports this
check so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import List

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator_conflicts_types import (
    ValidationIssue,
    _get_patterns,
    _is_broader_pattern,
)


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
