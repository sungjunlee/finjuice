"""Suggested-rule candidate payload helpers for `finjuice rules suggest`.

Owns rule-name sanitization, Banksalad category/tag defaults, and the compact
``suggested_rule`` dict used in JSON output. Payment-gateway classification
lives in :mod:`finjuice.pipeline.tagging.suggestion_scoring_classify`.
Merchant-context assembly stays in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import re
from typing import Any

from finjuice.pipeline.tagging.suggestion_similarity import _normalize_text

SUGGESTED_RULE_PRIORITY = 80
RECURRING_PRIORITY_BOOST = 5


def _banksalad_category_parts(
    suggestion: dict[str, Any],
) -> tuple[str, str]:
    """Return normalized (major, minor) Banksalad category parts."""
    category = suggestion.get("banksalad_category") or {}
    major = _normalize_text(category.get("major")) or ""
    minor = _normalize_text(category.get("minor")) or ""
    return major, minor


def _default_category_from_suggestion(suggestion: dict[str, Any]) -> str:
    """Return the category value used when auto-applying a suggestion."""
    major, minor = _banksalad_category_parts(suggestion)
    return minor or major


def _default_tags_from_suggestion(suggestion: dict[str, Any]) -> list[str]:
    """Return raw Banksalad categories as tags for auto-applied rules."""
    major, minor = _banksalad_category_parts(suggestion)
    tags: list[str] = []
    for candidate in [minor, major]:
        if candidate and candidate not in tags:
            tags.append(candidate)
    return tags or ["미분류"]


def _deduplicate_rule_name(base_name: str, existing_names: set[str]) -> str:
    """Add a numeric suffix if *base_name* already exists."""
    if base_name not in existing_names:
        return base_name
    for seq in range(2, 100):
        candidate = f"{base_name}_{seq}"
        if candidate not in existing_names:
            return candidate
    return f"{base_name}_99"


def _sanitize_rule_name(merchant: str) -> str:
    """
    Sanitize merchant name for use as a rule name.

    Args:
        merchant: Raw merchant name

    Returns:
        Sanitized name suitable for YAML rule identifier
    """
    # Convert to lowercase and replace non-alphanumeric (including Korean) with underscore
    name_base = re.sub(r"[^a-zA-Z0-9가-힣]", "_", merchant.lower())
    # Collapse multiple underscores
    name_base = re.sub(r"_+", "_", name_base).strip("_")
    # Limit length
    return name_base[:30] if name_base else "unknown"


def get_suggested_rule_name(merchant: str) -> str:
    """Build the persisted rule name for a suggestion merchant."""
    return f"suggested_{_sanitize_rule_name(merchant)}"


def build_suggested_rule_field(
    suggestion: dict[str, Any],
    existing_names: set[str],
) -> dict[str, Any]:
    """Build a compact ``suggested_rule`` dict for JSON output.

    The returned dict is directly usable as ``rules add`` arguments.
    """
    merchant = str(suggestion["merchant"])
    base_name = get_suggested_rule_name(merchant)
    name = _deduplicate_rule_name(base_name, existing_names)

    category = _default_category_from_suggestion(suggestion)
    tags = _default_tags_from_suggestion(suggestion)
    priority = SUGGESTED_RULE_PRIORITY
    if suggestion.get("is_recurring"):
        priority += RECURRING_PRIORITY_BOOST

    rule: dict[str, Any] = {
        "name": name,
        "match": str(suggestion["pattern"]),
        "category": category or "미분류",
        "tags": tags,
        "priority": priority,
    }
    return rule
