"""Diagnostic format and suggestion helpers for tagging rule validation.

Owns rule labels, Did-you-mean hints, and suggestion-message assembly used by
schema validation. Condition and conflict validators stay in
:mod:`finjuice.pipeline.tagging.validator`, which re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

import difflib
from typing import Any, Final

# Common alias map for operator typos that difflib's edit-distance misses.
# Keeps the user-facing suggestion reliable for frequent mistakes.
_OPERATOR_ALIASES: Final = {
    "equal": "is",
    "equals": "is",
    "eq": "is",
    "ne": "is_not",
    "notequal": "is_not",
    "lt": "less_than",
    "gt": "greater_than",
    "matches": "regex",
    "startswith": "starts_with",
    "start_with": "starts_with",
    "contain": "contains",
    "has": "contains",
    "in_range": "between",
}


def _candidate_rule_name(rule_dict: Any, rule_index: int) -> str:
    """Best-effort rule name for diagnostics, even when validation fails."""
    fallback_name = f"UNNAMED_RULE_{rule_index}"
    if not isinstance(rule_dict, dict):
        return fallback_name

    raw_name = rule_dict.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    if raw_name is None:
        return fallback_name
    return str(raw_name)


def _format_rule_label(rule_name: str, rule_index: int | None = None) -> str:
    """Format a rule label for human-readable validation errors."""
    if rule_index is None:
        return f"Rule '{rule_name}'"
    return f"Rule '{rule_name}' (#{rule_index})"


def _format_condition_context(
    rule_name: str,
    condition_index: int,
    *,
    rule_index: int | None = None,
) -> str:
    """Format a condition-specific validation context string."""
    return f"{_format_rule_label(rule_name, rule_index)} condition at index {condition_index}"


def _format_did_you_mean(value: str, candidates: set[str]) -> str | None:
    """Return a short Did-you-mean hint for a mistyped token.

    Tries an alias map first (catches common substitutions like `equal` -> `is`
    that fall below difflib's similarity threshold), then falls back to
    edit-distance matching against the allowed candidates.
    """
    alias = _OPERATOR_ALIASES.get(value.lower())
    if alias and alias in candidates:
        return f"Did you mean: '{alias}'?"
    matches = difflib.get_close_matches(value, sorted(candidates), n=2, cutoff=0.6)
    if not matches:
        return None
    return f"Did you mean: '{matches[0]}'?"


def _extract_suggestion(exc: ValueError) -> str | None:
    """Extract an optional suggestion from internal validation exceptions."""
    return getattr(exc, "suggestion", None)


def _append_suggestion(message: str, suggestion: str | None) -> str:
    """Append a suggestion to a strict-mode error message when available."""
    if not suggestion:
        return message
    return f"{message}\n{suggestion}"
