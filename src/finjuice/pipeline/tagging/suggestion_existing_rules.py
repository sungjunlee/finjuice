"""Existing-rule lookup helpers for `finjuice rules suggest`.

Owns loading of the persisted rules file (match segments and rule names) and
the duplicate-coverage check used to skip merchants that an existing rule
already handles.

:mod:`finjuice.pipeline.tagging.suggestion_scoring` re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from finjuice.pipeline.tagging.rules_yaml_io import load_rules


def _load_existing_patterns(rules_file: Optional[Path]) -> set[str]:
    """Load normalized rule match segments to avoid duplicate suggestions."""
    if not rules_file or not rules_file.exists():
        return set()

    patterns: set[str] = set()
    for rule in load_rules(rules_file):
        for segment in rule.match.split("|"):
            normalized = segment.strip().lower()
            if normalized:
                patterns.add(normalized)
    return patterns


def _load_existing_rule_names(rules_file: Optional[Path]) -> set[str]:
    """Load existing rule names to detect conflicts."""
    if not rules_file or not rules_file.exists():
        return set()
    return {rule.name for rule in load_rules(rules_file)}


def _should_skip_existing_rule(
    merchant: str,
    match_pattern: str,
    existing_patterns: set[str],
) -> bool:
    """Return True when a merchant already appears covered by an existing rule."""
    merchant_lower = merchant.lower()
    pattern_lower = match_pattern.lower()

    if merchant_lower in existing_patterns or pattern_lower in existing_patterns:
        return True

    return any(
        existing in merchant_lower or existing in pattern_lower or pattern_lower in existing
        for existing in existing_patterns
    )
