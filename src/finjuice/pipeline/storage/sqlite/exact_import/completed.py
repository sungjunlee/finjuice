"""Completed-import lookup interpretation and no-op/conflict outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand, ImportCounts
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome

JSONValue = Any
_REINTERPRET_MESSAGE = (
    "Re-interpretation of an identical source artifact requires an explicit correction path."
)


def completed_outcome(
    command: ExactImportCommand,
    records: tuple[Mapping[str, JSONValue], ...],
) -> MutationOutcome | None:
    """Return a no-op outcome, raise on conflict, or None when no completed import exists."""
    if not records:
        return None
    payload = _unique_completed_payload(records)
    _reject_changed_interpretation(command, payload)
    counts = _counts_from_manifest(payload)
    occurrence_id = str(payload["ids"]["occurrence_id"])
    artifact_id = str(records[0]["artifact_id"])
    result: dict[str, JSONValue] = {
        "artifact_id": artifact_id,
        "completed": True,
        "counts": _noop_counts(counts),
        "noop": True,
        "occurrence_id": occurrence_id,
        "transaction_ids": list(payload["ids"].get("transaction_ids", [])),
    }
    if command.preview:
        result["completed"] = False
    return MutationOutcome(result=result)


def _unique_completed_payload(
    records: tuple[Mapping[str, JSONValue], ...],
) -> Mapping[str, JSONValue]:
    payloads = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise MutationValidationError("Exact import completion marker is malformed.")
        payloads.append(payload)
    if len(payloads) != 1:
        raise MutationValidationError("Exact import completion marker is ambiguous.")
    payload = payloads[0]
    ids = payload.get("ids")
    if not isinstance(ids, Mapping) or not ids.get("occurrence_id"):
        raise MutationValidationError("Exact import completion marker is malformed.")
    return payload


def _reject_changed_interpretation(
    command: ExactImportCommand,
    payload: Mapping[str, JSONValue],
) -> None:
    request = command.payload()
    if payload.get("intent") != request["intent"]:
        raise MutationConflictError(_REINTERPRET_MESSAGE)
    if payload.get("import_policy_version") != request["import_policy_version"]:
        raise MutationConflictError(_REINTERPRET_MESSAGE)
    if payload.get("parser_policy_version") != request["parser_policy_version"]:
        raise MutationConflictError(_REINTERPRET_MESSAGE)


def _counts_from_manifest(payload: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        raise MutationValidationError("Exact import completion marker is malformed.")
    return dict(counts)


def _noop_counts(counts: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    reused = ImportCounts()
    for family in ("transactions", "assets", "overview"):
        stored = counts.get(family)
        if not isinstance(stored, Mapping):
            continue
        target = getattr(reused, family)
        target.reused = int(stored.get("inserted", 0)) + int(stored.get("reused", 0))
        target.quarantined = int(stored.get("quarantined", 0))
        target.unsupported = int(stored.get("unsupported", 0))
    reused.unknown_sheets = int(counts.get("unknown_sheets", 0))
    reused.uncovered_rows = int(counts.get("uncovered_rows", 0))
    mapper_status = counts.get("mapper_status")
    if isinstance(mapper_status, Mapping):
        reused.mapper_status = {str(key): str(value) for key, value in mapper_status.items()}
    return reused.as_dict()
