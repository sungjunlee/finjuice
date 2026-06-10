"""Decision rules for the ``finjuice status`` command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.schema_registry import (
    SchemaCompatibilityState,
    get_schema_migration_guidance,
)

from .compute import StatusFacts

LOW_REMAINDER_MIN_COVERAGE_PCT = 99.0
LOW_REMAINDER_MAX_UNTAGGED = 5


@dataclass(frozen=True)
class StatusDiagnoses:
    """Decision output derived from status facts."""

    health: dict[str, Any]
    actionable: bool
    signals: dict[str, Any]
    next_steps: list[dict[str, str]]


def diagnose_status(facts: StatusFacts) -> StatusDiagnoses:
    """Derive status health, signals, and next-step cues from collected facts."""
    health = _compute_status_health(
        rules_exists=facts.rules_exists,
        schema_state=facts.schema_summary.state,
        suggestable_untagged_count=facts.suggestable_untagged_count,
        suggestable_tagging_rate=facts.suggestable_tagging_rate,
        transfer_excluded_untagged_count=facts.transfer_excluded_untagged_count,
    )
    return StatusDiagnoses(
        health=health,
        actionable=health["status"] != "ok",
        signals={
            "rules_file_exists": facts.rules_exists,
            "tagging_rate": facts.tagging_rate,
            "untagged_count": facts.untagged_count,
            "filters_applied": facts.filters_applied,
            "detailed_requested": facts.detailed_requested,
        },
        next_steps=_build_status_next_steps(
            facts=facts,
            rules_exists=facts.rules_exists,
            untagged_count=facts.untagged_count,
            suggestable_untagged_count=facts.suggestable_untagged_count,
            transfer_excluded_untagged_count=facts.transfer_excluded_untagged_count,
        ),
    )


def _compute_status_health(
    *,
    rules_exists: bool,
    schema_state: SchemaCompatibilityState,
    suggestable_untagged_count: int,
    suggestable_tagging_rate: float,
    transfer_excluded_untagged_count: int,
) -> dict[str, Any]:
    """Return the additive health object for status JSON."""
    if schema_state is SchemaCompatibilityState.UNSUPPORTED:
        return {"status": "critical", "reasons": ["unsupported_schema"]}

    if not rules_exists:
        return {"status": "critical", "reasons": ["missing_rules_file"]}

    if schema_state is SchemaCompatibilityState.COMPATIBLE_LEGACY:
        reasons = ["compatible_legacy_schema"]
        if suggestable_untagged_count > 0:
            reasons.append("untagged_transactions")
        return {"status": "warning", "reasons": reasons}

    if suggestable_untagged_count == 0:
        reasons = ["transfer_excluded_untagged"] if transfer_excluded_untagged_count > 0 else []
        return {"status": "ok", "reasons": reasons}

    if (
        suggestable_tagging_rate >= LOW_REMAINDER_MIN_COVERAGE_PCT
        and suggestable_untagged_count <= LOW_REMAINDER_MAX_UNTAGGED
    ):
        return {"status": "ok", "reasons": ["low_untagged_remainder"]}

    return {"status": "warning", "reasons": ["untagged_transactions"]}


def _build_status_next_steps(
    *,
    facts: StatusFacts,
    rules_exists: bool,
    untagged_count: int,
    suggestable_untagged_count: int,
    transfer_excluded_untagged_count: int,
) -> list[dict[str, str]]:
    """Return additive next-step cues for agent consumers."""
    schema_next_steps: list[dict[str, str]] = []
    if facts.schema_summary.state is SchemaCompatibilityState.COMPATIBLE_LEGACY:
        guidance = get_schema_migration_guidance(
            facts.schema_summary,
            metadata_dir=facts.data_dir / "metadata",
        )
        schema_next_steps.append(
            {
                "signal": "compatible_legacy_schema",
                "message": guidance["message"],
                "command": guidance["command"],
            }
        )
    elif facts.schema_summary.state is SchemaCompatibilityState.UNSUPPORTED:
        guidance = get_schema_migration_guidance(
            facts.schema_summary,
            metadata_dir=facts.data_dir / "metadata",
        )
        schema_next_steps.append(
            {
                "signal": "unsupported_schema",
                "message": guidance["message"],
                "command": guidance["command"],
            }
        )

    if not rules_exists:
        return [
            *schema_next_steps,
            {
                "signal": "missing_rules_file",
                "message": "Initialize finjuice before relying on tagging coverage.",
                "command": "finjuice init",
            },
        ]

    if suggestable_untagged_count > 0:
        return [
            *schema_next_steps,
            {
                "signal": "untagged_transactions",
                "message": "Inspect the current review queue before editing rules.",
                "command": "finjuice review --json",
            },
            {
                "signal": "retag_after_rules",
                "message": "Re-apply existing rules after reviewing the queue.",
                "command": "finjuice tag",
            },
        ]

    if untagged_count > 0 and transfer_excluded_untagged_count > 0:
        return [
            *schema_next_steps,
            {
                "signal": "transfer_excluded_untagged",
                "message": "Untagged transfer rows are excluded from rule suggestions.",
                "command": "finjuice review --json --untagged",
            },
        ]

    return schema_next_steps
