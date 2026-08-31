"""Compact privacy-projection helpers for `finjuice rules suggest`.

Owns non-PII suggestion shaping used by the compact privacy profile.
JSON compute and the domain error stay in
:mod:`finjuice.pipeline.tagging.suggest_compute`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any


def _compact_suggested_rule(rule: dict[str, Any] | None) -> dict[str, Any]:
    """Return non-PII fields from a suggested rule payload."""
    if not rule:
        return {}
    compact: dict[str, Any] = {}
    for key in ("category", "tags", "priority"):
        if key in rule:
            compact[key] = rule[key]
    return compact


def _compact_rule_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Return compact workflow cues for one rule suggestion."""
    similar_merchants = suggestion.get("similar_merchants") or []
    active_months = suggestion.get("active_months") or []
    return {
        "transaction_count": int(suggestion.get("transaction_count") or 0),
        "active_month_count": len(active_months),
        "is_recurring": bool(suggestion.get("is_recurring")),
        "banksalad_category": suggestion.get("banksalad_category"),
        "time_patterns": suggestion.get("time_patterns"),
        "similar_merchant_count": len(similar_merchants),
        "merchant_kind": suggestion.get("merchant_kind"),
        "ambiguous_reason": suggestion.get("ambiguous_reason"),
        "default_action": suggestion.get("default_action"),
        "auto_apply_eligible": bool(suggestion.get("auto_apply_eligible", True)),
        "suggested_rule": _compact_suggested_rule(suggestion.get("suggested_rule")),
    }


def _compact_rules_suggest_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return `rules suggest` JSON without merchant-level PII samples."""
    compact = {
        key: value
        for key, value in result.items()
        if key not in {"rules_file", "suggestions", "would_apply"}
    }
    suggestions = result.get("suggestions")
    if isinstance(suggestions, list):
        compact["suggestion_count"] = len(suggestions)
        compact["suggestions"] = [
            _compact_rule_suggestion(suggestion)
            for suggestion in suggestions
            if isinstance(suggestion, dict)
        ]

    would_apply = result.get("would_apply")
    if isinstance(would_apply, list):
        compact["would_apply"] = [
            {"rule": _compact_suggested_rule(item.get("rule"))}
            for item in would_apply
            if isinstance(item, dict)
        ]
    auto_apply_skipped = result.get("auto_apply_skipped")
    if isinstance(auto_apply_skipped, list):
        compact["auto_apply_skipped"] = [
            {
                "reason": item.get("reason"),
                "default_action": item.get("default_action"),
            }
            for item in auto_apply_skipped
            if isinstance(item, dict)
        ]
    return compact
