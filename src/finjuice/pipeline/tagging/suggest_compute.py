"""JSON payload computation for `finjuice rules suggest`.

The Typer command module owns interactive apply and terminal rendering.
This module owns coverage-stat shaping, compact privacy projection, and the
`--json` payload used by `rules suggest`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)

TRANSFER_EXCLUSION_DESCRIPTION = (
    "Only rows where is_transfer == 1 and transfer_group_id is present are excluded; "
    "unconfirmed transfer candidates remain suggestable."
)


class SuggestComputeError(Exception):
    """Domain failure for `rules suggest` compute; CLI maps it to emit_error."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        exit_code: int,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.exit_code = exit_code
        self.suggestion = suggestion


def _fail(
    message: str,
    *,
    error_code: str,
    exit_code: int,
    suggestion: str | None = None,
) -> None:
    raise SuggestComputeError(
        message,
        error_code=error_code,
        exit_code=exit_code,
        suggestion=suggestion,
    )


def _stats_int(stats: dict[str, Any], key: str, fallback: int = 0) -> int:
    """Read an integer coverage stat with fallback for older test doubles."""
    return int(stats.get(key, fallback) or 0)


def _stats_float(stats: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    """Read a float coverage stat with fallback for older test doubles."""
    return float(stats.get(key, fallback) or 0.0)


def _augment_suggestion_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Add explicit transfer-exclusion fields while keeping legacy stat keys."""
    total_count = _stats_int(stats, "total_count")
    untagged_count = _stats_int(stats, "untagged_count")
    suggestable_total_count = _stats_int(stats, "suggestable_total_count", total_count)
    suggestable_untagged_count = _stats_int(
        stats,
        "suggestable_untagged_count",
        untagged_count,
    )
    transfer_excluded_count = _stats_int(
        stats,
        "transfer_excluded_count",
        max(total_count - suggestable_total_count, 0),
    )
    transfer_excluded_untagged_count = _stats_int(
        stats,
        "transfer_excluded_untagged_count",
        max(untagged_count - suggestable_untagged_count, 0),
    )
    coverage_before = _stats_float(stats, "coverage_before_pct")
    suggestable_coverage_before = _stats_float(
        stats,
        "suggestable_coverage_before_pct",
        coverage_before,
    )

    return {
        **stats,
        "total_count": total_count,
        "untagged_count": untagged_count,
        "suggestable_total_count": suggestable_total_count,
        "suggestable_untagged_count": suggestable_untagged_count,
        "transfer_excluded_count": transfer_excluded_count,
        "transfer_excluded_untagged_count": transfer_excluded_untagged_count,
        "coverage_before_pct": round(float(coverage_before), 2),
        "suggestable_coverage_before_pct": round(float(suggestable_coverage_before), 2),
    }


def _suggest_transfer_exclusions(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the transfer-exclusion explanation for `rules suggest` JSON."""
    return {
        "excluded_count": _stats_int(stats, "transfer_excluded_count"),
        "excluded_untagged_count": _stats_int(stats, "transfer_excluded_untagged_count"),
        "definition": TRANSFER_EXCLUSION_DESCRIPTION,
    }


def _rules_suggest_count_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the shared additive count payload for `rules suggest`."""
    return {
        "untagged_count": _stats_int(stats, "untagged_count"),
        "suggestable_untagged_count": _stats_int(stats, "suggestable_untagged_count"),
        "total_count": _stats_int(stats, "total_count"),
        "suggestable_total_count": _stats_int(stats, "suggestable_total_count"),
        "transfer_exclusions": _suggest_transfer_exclusions(stats),
        "coverage_before_pct": round(_stats_float(stats, "coverage_before_pct"), 2),
        "suggestable_coverage_before_pct": round(
            _stats_float(stats, "suggestable_coverage_before_pct"),
            2,
        ),
    }


def _append_applied_suggestion_audit(
    on_applied: Callable[[str], None] | None,
    rule_name: str,
) -> None:
    """Notify the CLI that a suggestion rule was applied."""
    if on_applied is not None:
        on_applied(rule_name)


def _compute_rules_suggest_json(
    config: Config,
    top_n: int,
    min_count: int,
    apply: bool,
    yes: bool,
    tag_after: bool,
    preview: bool,
    dry_run: bool,
    json_output: bool,
    file_id: str | None = None,
    on_applied: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Compute JSON payload for `rules suggest`."""
    from finjuice.pipeline.tagging.suggestions import (
        apply_suggestion_to_rules,
        build_rule_dict_from_suggestion,
        generate_merchant_context,
        get_suggestion_coverage_stats,
        is_auto_apply_eligible,
    )

    if not config.csv_base_dir.exists():
        if config.data_dir.exists():
            _fail(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice ingest' to import XLSX files.",
                error_code="NO_DATA",
                exit_code=4,
                suggestion="finjuice ingest",
            )
        else:
            _fail(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice init' to set up, then 'finjuice ingest'.",
                error_code="DATA_DIR_NOT_INITIALIZED",
                exit_code=2,
                suggestion="finjuice init",
            )

    if dry_run and not apply:
        _fail(
            "Cannot use --dry-run without --apply.",
            error_code="INVALID_ARGS",
            exit_code=2,
        )

    if apply and not yes and not dry_run:
        _fail(
            "Cannot use --apply with --json in interactive mode. "
            "Use --apply --yes for headless operation.",
            error_code="INVALID_ARGS",
            exit_code=2,
        )

    stats = _augment_suggestion_stats(
        get_suggestion_coverage_stats(config.data_dir, file_id=file_id)
    )
    if file_id is not None and _stats_int(stats, "total_count") == 0:
        _fail(
            f"No transactions found for file_id '{file_id}'.",
            error_code="NO_DATA",
            exit_code=4,
        )
    untagged_count = _stats_int(stats, "untagged_count")
    suggestable_untagged_count = _stats_int(stats, "suggestable_untagged_count")
    coverage_before = _stats_float(stats, "coverage_before_pct")

    if suggestable_untagged_count == 0:
        if untagged_count > 0:
            message = "No suggestable untagged transactions after excluding transfers."
        else:
            message = "All transactions are tagged."
        result: dict[str, Any] = {
            **_rules_suggest_count_payload(stats),
            "suggestions": [],
            "message": message,
        }
        if apply and dry_run:
            result.update(
                {
                    "dry_run": True,
                    "rules_file": str(config.rules_file),
                    "rules_file_modified": False,
                    "would_apply": [],
                    "message": "Dry run: no changes made",
                }
            )
        return result

    suggestions = generate_merchant_context(
        data_dir=config.data_dir,
        rules_file=config.rules_file,
        top_n=top_n,
        min_count=min_count,
        file_id=file_id,
    )
    auto_apply_suggestions = [
        suggestion for suggestion in suggestions if is_auto_apply_eligible(suggestion)
    ]
    auto_apply_skipped = [
        suggestion for suggestion in suggestions if not is_auto_apply_eligible(suggestion)
    ]

    if apply and dry_run:
        return {
            "dry_run": True,
            "rules_file": str(config.rules_file),
            "rules_file_modified": False,
            **_rules_suggest_count_payload(stats),
            "suggestions": suggestions,
            "auto_apply_skipped": [
                {
                    "merchant": suggestion["merchant"],
                    "reason": suggestion.get("ambiguous_reason") or "not_auto_apply_eligible",
                    "default_action": suggestion.get("default_action"),
                }
                for suggestion in auto_apply_skipped
            ],
            "would_apply": [
                {
                    "merchant": suggestion["merchant"],
                    "rule": build_rule_dict_from_suggestion(suggestion),
                }
                for suggestion in auto_apply_suggestions
            ],
            "message": "Dry run: no changes made",
        }

    if apply and yes:
        from finjuice.pipeline.tagging.pipeline import run_tagging

        applied_count = 0
        skipped_count = 0

        for suggestion_idx, suggestion in enumerate(suggestions, start=1):
            if not is_auto_apply_eligible(suggestion):
                skipped_count += 1
                continue
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_applied_suggestion_audit(on_applied, applied_rule.name)
                applied_count += 1
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Failed to auto-apply suggestion %s/%s (%s)",
                    suggestion_idx,
                    len(suggestions),
                    type(exc).__name__,
                )
                skipped_count += 1

        coverage_after = coverage_before
        if tag_after and applied_count > 0:
            tag_result = run_tagging(
                csv_base_dir=config.csv_base_dir,
                rules_path=config.rules_file,
                dry_run=False,
            )
            coverage_after = float(tag_result.get("coverage_pct", coverage_before))

        return {
            "applied": applied_count,
            "skipped": skipped_count,
            "auto_apply_skipped": len(auto_apply_skipped),
            **_rules_suggest_count_payload(stats),
            "coverage_before_pct": round(float(coverage_before), 2),
            "coverage_after_pct": round(float(coverage_after), 2),
        }

    return {
        **_rules_suggest_count_payload(stats),
        "suggestions": suggestions,
    }


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
