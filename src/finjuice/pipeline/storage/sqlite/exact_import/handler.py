"""MutationContext handler for one exact XLSX file import."""

from __future__ import annotations

from finjuice.pipeline.storage.sqlite.exact_import.completed import completed_outcome
from finjuice.pipeline.storage.sqlite.exact_import.mapping import map_captured_workbook
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand
from finjuice.pipeline.storage.sqlite.exact_import.persist import persist_new_import
from finjuice.pipeline.storage.sqlite.exact_import.plan import build_import_plan
from finjuice.pipeline.storage.sqlite.mutations import MutationContext, MutationOutcome


def apply_exact_import(context: MutationContext, command: ExactImportCommand) -> MutationOutcome:
    """Look up prior identity, then preview or persist one file-level import."""
    existing = context.find_completed_exact_imports(command.capture.digest_hex)
    completed = completed_outcome(command, existing)
    if completed is not None:
        return completed
    mappings = map_captured_workbook(command)
    overlap = context.load_transaction_identity_snapshot()
    plan = build_import_plan(command.capture.evidence, mappings, overlap)
    if command.preview:
        return MutationOutcome(result=_preview_result(plan.counts.as_dict(), command))
    return persist_new_import(context, command, mappings, plan)


def _preview_result(counts: dict[str, object], command: ExactImportCommand) -> dict[str, object]:
    return {
        "artifact_id": command.capture.artifact_id,
        "completed": False,
        "counts": counts,
        "noop": False,
        "occurrence_id": None,
        "transaction_ids": [],
    }
