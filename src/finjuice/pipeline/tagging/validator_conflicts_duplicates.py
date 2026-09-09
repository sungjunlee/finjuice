"""Duplicate-name conflict check for loaded tagging rules.

Owns :func:`check_duplicate_names`. The orchestrator
:func:`~finjuice.pipeline.tagging.validator_conflicts.validate_rules` stays in
:mod:`finjuice.pipeline.tagging.validator_conflicts` and re-exports this
check so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import List

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator_conflicts import ValidationIssue


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
