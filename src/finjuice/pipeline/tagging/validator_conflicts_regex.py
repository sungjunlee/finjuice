"""Regex-validity conflict check for loaded tagging rules.

Owns :func:`check_regex_validity`. The orchestrator
:func:`~finjuice.pipeline.tagging.validator_conflicts.validate_rules` stays in
:mod:`finjuice.pipeline.tagging.validator_conflicts` and re-exports this
check so existing callers can keep importing from that module.
"""

from __future__ import annotations

import re
from typing import List

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator_conflicts import ValidationIssue


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
