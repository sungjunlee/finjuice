"""Detached review input selection and best-effort canonical rule notes."""

from __future__ import annotations

from typing import Any

import polars as pl

from finjuice.pipeline.analysis_source import analysis_frame, analysis_metadata
from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

_NOTES_WARNING = "Canonical rule notes are unavailable; transaction review is unchanged."


def repository_review_frame(
    snapshot: AnalysisReadSnapshot, *, month: str | None, all_history: bool
) -> tuple[pl.DataFrame | None, str | None, dict[str, Any]]:
    """Select legacy partition scope without applying report filters."""
    months = snapshot.transactions.partition_months
    selected = None if all_history else month or (months[-1] if months else None)
    metadata = dict(analysis_metadata(snapshot, "legacy_review.v1", month=selected))
    if not all_history and (selected is None or selected not in months):
        return None, selected, metadata
    frame = analysis_frame(snapshot, month=selected)
    if all_history and not months and frame.is_empty():
        return None, None, metadata
    return frame, selected, metadata


def repository_review_notes(
    snapshot: AnalysisReadSnapshot, metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return pinned enabled notes or a static, explicit availability warning."""
    selection = snapshot.rules
    if selection.selection_state == "absent" and not selection.revisions:
        return []
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        metadata["rule_notes_warning"] = _NOTES_WARNING
        return []
    try:
        rules = load_rules_bytes(head.content)
        notes = []
        for rule in rules:
            if not rule.enabled or not rule.notes.strip():
                continue
            item = {"rule_name": rule.name, "notes": rule.notes.strip(), "tags": list(rule.tags)}
            if rule.category:
                item["category"] = rule.category
            notes.append(item)
            if len(notes) == 5:
                break
        return notes
    except Exception:
        metadata["rule_notes_warning"] = _NOTES_WARNING
        return []


def render_repository_review_identity(metadata: dict[str, Any]) -> None:
    """Show source identity and unavailable notes in human output."""
    from finjuice.pipeline.cli.output import info, warning

    if not metadata:
        return
    info(
        f"Repository revision {metadata['dataset_revision']} "
        f"({metadata['dataset_generation']}); policy legacy_review.v1"
    )
    if metadata.get("rule_notes_warning"):
        warning(str(metadata["rule_notes_warning"]))
