"""Existing-rule lookup helpers for `finjuice rules suggest`.

Owns loading of the persisted rules file (match segments and rule names) and
the duplicate-coverage check used to skip merchants that an existing rule
already handles.

:mod:`finjuice.pipeline.tagging.suggestion_scoring` re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Optional

from finjuice.pipeline.tagging.models import TagRule


def _load_existing_patterns(rules_file: Optional[Path]) -> set[str]:
    """Load normalized rule match segments to avoid duplicate suggestions."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules

    if not rules_file or not rules_file.exists():
        return set()

    return existing_rule_context(load_rules(rules_file))[0]


def _load_existing_rule_names(rules_file: Optional[Path]) -> set[str]:
    """Load existing rule names to detect conflicts."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules

    if not rules_file or not rules_file.exists():
        return set()
    return existing_rule_context(load_rules(rules_file))[1]


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


def existing_rule_context(rules: Iterable[TagRule]) -> tuple[set[str], set[str]]:
    """Extract legacy pattern suppression and name collision sets from loaded rules."""
    patterns: set[str] = set()
    names: set[str] = set()
    for rule in rules:
        names.add(rule.name)
        for segment in rule.match.split("|"):
            normalized = segment.strip().lower()
            if normalized:
                patterns.add(normalized)
    return patterns, names
