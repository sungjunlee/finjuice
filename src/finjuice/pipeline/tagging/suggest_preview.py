"""Read-only suggestion payload assembly shared by both storage authorities."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.tagging.suggest_compute_stats import (
    _rules_suggest_count_payload,
    _stats_int,
)


def build_suggestion_preview(
    stats: dict[str, Any],
    suggestions: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    rules_file: str | None = None,
) -> dict[str, Any]:
    """Preserve count, eligibility and dry-run shapes without invoking any writer."""
    from finjuice.pipeline.tagging.suggestions import (
        build_rule_dict_from_suggestion,
        is_auto_apply_eligible,
    )

    result: dict[str, Any] = {
        **_rules_suggest_count_payload(stats),
        "suggestions": suggestions,
    }
    no_candidates = _stats_int(stats, "suggestable_untagged_count") == 0
    if no_candidates:
        result["message"] = (
            "No suggestable untagged transactions after excluding transfers."
            if _stats_int(stats, "untagged_count") > 0
            else "All transactions are tagged."
        )
    if not dry_run:
        return result
    result.update(
        dry_run=True,
        rules_file=rules_file,
        rules_file_modified=False,
        would_apply=[
            {
                "merchant": suggestion["merchant"],
                "rule": build_rule_dict_from_suggestion(suggestion),
            }
            for suggestion in suggestions
            if is_auto_apply_eligible(suggestion)
        ],
        message="Dry run: no changes made",
    )
    if not no_candidates:
        result["auto_apply_skipped"] = [
            {
                "merchant": suggestion["merchant"],
                "reason": suggestion.get("ambiguous_reason") or "not_auto_apply_eligible",
                "default_action": suggestion.get("default_action"),
            }
            for suggestion in suggestions
            if not is_auto_apply_eligible(suggestion)
        ]
    return result
