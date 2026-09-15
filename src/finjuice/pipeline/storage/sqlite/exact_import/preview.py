"""Pure exact-import preview over explicitly requested, pinned lookup evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.exact_import.mapping import ExactWorkbookMappings
    from finjuice.pipeline.storage.sqlite.exact_import.models import ImportPlan
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome


@dataclass(frozen=True)
class ImportPreviewSnapshot:
    """Detached lookups; a missing digest key is unrequested, not proven absent."""

    info: RepositoryInfo
    transaction_identities: tuple[dict[str, Any], ...]
    completed_by_digest: dict[str, tuple[dict[str, Any], ...]]
    statement_results: dict[str, dict[str, Any]] = field(default_factory=dict)


def preview_captured_import(
    command: ExactImportCommand, snapshot: ImportPreviewSnapshot
) -> MutationOutcome:
    """Reuse completion and mapping policy without database or object-store writes."""
    from finjuice.pipeline.storage.sqlite.exact_import.completed import completed_outcome
    from finjuice.pipeline.storage.sqlite.exact_import.handler import _preview_result
    from finjuice.pipeline.storage.sqlite.exact_import.mapping import map_captured_workbook
    from finjuice.pipeline.storage.sqlite.exact_import.plan import build_import_plan
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome

    if not command.preview:
        raise MutationValidationError("Detached import preview requires preview intent.")
    digest = command.capture.digest_hex
    if digest not in snapshot.completed_by_digest:
        raise MutationValidationError("Import digest was not requested in this snapshot.")
    completed = completed_outcome(command, deepcopy(snapshot.completed_by_digest[digest]))
    if completed is not None:
        return completed
    mappings = map_captured_workbook(command)
    plan = build_import_plan(
        command.capture.evidence, mappings, deepcopy(snapshot.transaction_identities)
    )
    return MutationOutcome(result=_preview_result(plan.counts.as_dict(), command))


def previewed_outcome(command: ExactImportCommand) -> MutationOutcome | None:
    """Reuse the completed-file policy for a successful earlier batch prediction."""
    from finjuice.pipeline.storage.sqlite.exact_import.completed import (
        _noop_counts,
        _reject_changed_interpretation,
    )
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome

    if command.preview_state is None:
        return None
    prior = command.preview_state.completed_by_digest.get(command.capture.digest_hex)
    if prior is None:
        return None
    _reject_changed_interpretation(command, prior)
    return MutationOutcome(
        result={
            "artifact_id": command.capture.artifact_id,
            "completed": False,
            "counts": _noop_counts(prior["counts"]),
            "noop": True,
            "occurrence_id": None,
            "transaction_ids": [],
        }
    )


def remember_preview(
    command: ExactImportCommand, mappings: ExactWorkbookMappings, plan: ImportPlan
) -> None:
    """Carry only planned inserts and completion counts forward in this batch."""
    from finjuice.pipeline.storage.sqlite.exact_import.overlap import transaction_effective_at
    from finjuice.pipeline.storage.sqlite.ids import new_entity_id

    state = command.preview_state
    if state is None:
        return
    inserted = {
        (item.sheet_name, item.source_row)
        for item in plan.decisions
        if item.family == "transactions" and item.action == "insert"
    }
    identities = []
    for row in mappings.transactions.rows:
        if (row.sheet_name, row.source_row) not in inserted:
            continue
        amount = row.interpreted_amount or row.source_amount
        assert amount is not None
        identities.append(
            {
                "transaction_id": new_entity_id(),
                "type_norm": row.type_norm,
                "coefficient": amount.coefficient,
                "scale": amount.scale,
                "currency_code": amount.currency,
                "currency_unknown": amount.currency_unknown,
                "effective_at": transaction_effective_at(row),
                "date_raw": row.date_raw or "",
                "time_raw": row.time_raw or "",
                "timezone_state": row.temporal.timezone_state,
            }
        )
    state.transaction_identities.extend(identities)
    state.completed_by_digest[command.capture.digest_hex] = {
        **command.payload(),
        "counts": plan.counts.as_dict(),
    }
