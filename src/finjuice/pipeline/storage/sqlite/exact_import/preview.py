"""Pure exact-import preview over explicitly requested, pinned lookup evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome


@dataclass(frozen=True)
class ImportPreviewSnapshot:
    """Detached lookups; a missing digest key is unrequested, not proven absent."""

    info: RepositoryInfo
    transaction_identities: tuple[dict[str, Any], ...]
    completed_by_digest: dict[str, tuple[dict[str, Any], ...]]


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
