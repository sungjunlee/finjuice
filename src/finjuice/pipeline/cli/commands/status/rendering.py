"""Payload assembly and Rich rendering for the ``finjuice status`` command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.storage.schema_registry import (
    SchemaCompatibilityState,
    get_schema_migration_guidance,
)

from .compute import StatusFacts
from .detector import StatusDiagnoses
from .rendering_detailed import (
    _format_currency,  # noqa: F401 — re-exported for existing rendering imports
    _render_detailed_amounts,  # noqa: F401 — re-exported for existing rendering imports
    _render_detailed_stats,
    _render_structural_sources,  # noqa: F401 — re-exported for existing rendering imports
    _render_top_categories,  # noqa: F401 — re-exported for existing rendering imports
)
from .rendering_next_steps import (
    TAGGING_TERMINOLOGY_REFERENCE,
    _render_next_steps,
    _render_status_footnotes,
)
from .rendering_table import (
    _add_data_rows,  # noqa: F401 — re-exported for existing rendering imports
    _add_import_row,  # noqa: F401 — re-exported for existing rendering imports
    _add_rules_row,  # noqa: F401 — re-exported for existing rendering imports
    _add_schema_row,  # noqa: F401 — re-exported for existing rendering imports
    _add_tagging_rate_row,  # noqa: F401 — re-exported for existing rendering imports
    _add_transfer_rows,  # noqa: F401 — re-exported for existing rendering imports
    _add_untagged_rows,  # noqa: F401 — re-exported for existing rendering imports
    _build_status_table,
    _tagging_rate_style,  # noqa: F401 — re-exported for existing rendering imports
)

__all__ = [
    "StatusRenderContext",
    "StatusResult",
    "build_status_result",
    "emit_status_result",
    "render_status",
]

TRANSFER_EXCLUSION_DESCRIPTION = (
    "Only rows where is_transfer == 1 and transfer_group_id is present are excluded; "
    "unconfirmed transfer candidates remain reportable."
)
STATUS_SCHEMA_REFERENCE = "schemas/status.schema.json"
TAGGING_TERMINOLOGY_DEFINITIONS = {
    "untagged": "tags_final is null or an empty tag array; transfer rows are included.",
    "suggestable_untagged": (
        "untagged rows eligible for rules suggest after excluding confirmed transfers."
    ),
    "uncategorized": "category_final is the fallback category 미분류.",
    "rule_matched": "tags_rule or category_rule contains rule-derived output.",
    "needs_review": "the explicit row flag needs_review == 1.",
}


@dataclass(frozen=True)
class StatusRenderContext:
    """Render-only context that should not be serialized in status JSON."""

    top_n: int
    filters_applied: int


@dataclass(frozen=True)
class StatusResult:
    """Computed status payload plus rendering metadata."""

    payload: dict[str, Any]
    render_context: StatusRenderContext


def build_status_result(facts: StatusFacts, diagnoses: StatusDiagnoses) -> StatusResult:
    """Assemble the public status payload from facts and diagnoses."""
    schema_payload: dict[str, Any] = {}
    if facts.repository is None:
        assert facts.schema_summary is not None
        schema_payload = facts.schema_summary.to_dict()
        if facts.schema_summary.state is not SchemaCompatibilityState.ACTIVE:
            schema_payload["migration"] = get_schema_migration_guidance(
                facts.schema_summary,
                metadata_dir=facts.data_dir / "metadata",
            )

    payload: dict[str, Any] = {
        "data_directory": {
            "path": facts.data_dir_resolved,
            "source": facts.data_dir_source,
        },
        "transactions": {
            "count": facts.total_rows,
            "date_range": {
                "start": facts.min_date,
                "end": facts.max_date,
            },
            "partition_count": facts.partition_count,
        },
        "schema": schema_payload,
        "last_import": {
            "imported_at": facts.last_import_date,
            "file_id": facts.last_import_file,
        },
        "terminology": {
            "reference": TAGGING_TERMINOLOGY_REFERENCE,
            "schema": STATUS_SCHEMA_REFERENCE,
            "definitions": dict(TAGGING_TERMINOLOGY_DEFINITIONS),
        },
        "tagging": {
            "tagged_count": facts.tagged_count,
            "untagged_count": facts.untagged_count,
            "tagging_rate": facts.tagging_rate,
            "suggestable_transaction_count": facts.suggestable_transaction_count,
            "suggestable_tagged_count": facts.suggestable_tagged_count,
            "suggestable_untagged_count": facts.suggestable_untagged_count,
            "suggestable_tagging_rate": facts.suggestable_tagging_rate,
            "transfer_candidate_count": facts.transfer_candidate_count,
            "transfer_excluded_count": facts.transfer_excluded_count,
            "transfer_excluded_untagged_count": facts.transfer_excluded_untagged_count,
            "unconfirmed_transfer_candidate_count": (facts.unconfirmed_transfer_candidate_count),
            "transfer_exclusions": {
                "excluded_count": facts.transfer_excluded_count,
                "confirmed_count": facts.transfer_excluded_count,
                "candidate_count": facts.transfer_candidate_count,
                "unconfirmed_candidate_count": facts.unconfirmed_transfer_candidate_count,
                "excluded_untagged_count": facts.transfer_excluded_untagged_count,
                "definition": TRANSFER_EXCLUSION_DESCRIPTION,
            },
            "untagged_merchants": facts.untagged_merchants,
            "untagged_merchants_total": facts.untagged_merchants_total,
        },
        "rules_file": {
            "path": str(facts.rules_path),
            "exists": facts.rules_exists,
            "modified_at": facts.rules_modified,
        },
    }
    if facts.repository is not None:
        repository = facts.repository
        payload["repository"] = repository
        payload["schema"] = {
            "authority": "repository",
            "state": "active",
            "current_version": repository["schema_version"],
            "sqlite_schema_version": repository["schema_version"],
        }
        payload["last_import"] = repository["last_import"]
        payload["transactions"]["source_counts"] = repository["source_counts"]
        payload["rules_file"] = {
            "path": None,
            "authority": "repository",
            "exists": repository["rules_head"]["parsed_status"] != "missing",
            "modified_at": repository["rules_head"]["updated_at"],
            **repository["rules_head"],
        }
    payload["health"] = diagnoses.health
    payload["actionable"] = diagnoses.actionable
    payload["signals"] = diagnoses.signals
    payload["next_steps"] = diagnoses.next_steps
    if facts.detailed_stats is not None or (
        facts.repository is not None and facts.detailed_stats_warning is not None
    ):
        payload["detailed_stats"] = facts.detailed_stats
        payload["detailed_stats_warning"] = facts.detailed_stats_warning

    return StatusResult(
        payload=payload,
        render_context=StatusRenderContext(
            top_n=facts.top_n,
            filters_applied=facts.filters_applied,
        ),
    )


def emit_status_result(result: StatusResult, *, json_output: bool) -> None:
    """Emit a computed status result in JSON or human-readable form."""
    if json_output:
        emit(
            result.payload,
            json_output=True,
            render_fn=lambda _: None,
            command="status",
            meta_extras={
                "filters_applied": result.render_context.filters_applied,
                **result.payload.get("repository", {}).get("metadata", {}),
            },
        )
        return

    render_status(result)


def render_status(status_result: StatusResult) -> None:
    """Render status data as Rich console output."""
    result = status_result.payload
    console.print("\n[bold cyan]📊 Finance Data Status[/bold cyan]\n")
    console.print(_build_status_table(result))
    _render_status_footnotes(status_result.render_context.filters_applied)

    detailed_stats = result.get("detailed_stats")
    detailed_warning = result.get("detailed_stats_warning")
    if "repository" in result and detailed_warning:
        # Canonical goals warnings describe partial configuration availability;
        # transaction analytics remain usable and must be shown alongside them.
        console.print(f"[yellow]{detailed_warning}[/yellow]")
        detailed_warning = None
    if detailed_stats:
        _render_detailed_stats(
            detailed_stats,
            detailed_warning,
            status_result.render_context.top_n,
        )

    _render_next_steps(
        rules_exists=result["rules_file"]["exists"],
        suggestable_untagged_count=result["tagging"]["suggestable_untagged_count"],
        transfer_excluded_untagged_count=result["tagging"]["transfer_excluded_untagged_count"],
        schema_migration=result["schema"].get("migration"),
        repository_steps=result["next_steps"] if "repository" in result else None,
    )
