"""JSON payload computation for `finjuice rules suggest`.

The Typer command module owns interactive apply and terminal rendering.
This module owns the `--json` payload used by `rules suggest`. Coverage-stat
shaping helpers live in :mod:`finjuice.pipeline.tagging.suggest_compute_stats`,
compact privacy projection lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_compact`, the domain error
lives in :mod:`finjuice.pipeline.tagging.suggest_compute_error`, and the
headless auto-apply loop lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_apply`; all are re-exported
here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.suggest_compute_apply import (
    _apply_auto_apply_suggestions,
)
from finjuice.pipeline.tagging.suggest_compute_compact import (
    _compact_rule_suggestion,  # noqa: F401 — re-exported for existing suggest_compute imports
    _compact_rules_suggest_result,  # noqa: F401 — re-exported for existing suggest_compute imports
    _compact_suggested_rule,  # noqa: F401 — re-exported for existing suggest_compute imports
)
from finjuice.pipeline.tagging.suggest_compute_error import (
    SuggestComputeError,  # noqa: F401 — re-exported for existing suggest_compute imports
    _fail,
)
from finjuice.pipeline.tagging.suggest_compute_stats import (
    TRANSFER_EXCLUSION_DESCRIPTION,  # noqa: F401 — re-exported for existing suggest_compute imports
    _augment_suggestion_stats,
    _rules_suggest_count_payload,
    _stats_float,
    _stats_int,
    _suggest_transfer_exclusions,  # noqa: F401 — re-exported for existing suggest_compute imports
)


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

        applied_count, skipped_count = _apply_auto_apply_suggestions(
            suggestions,
            rules_file=config.rules_file,
            audit_applied=partial(_append_applied_suggestion_audit, on_applied),
        )

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
