"""Write one accepted exact XLSX import inside the pinned mutation."""

from __future__ import annotations

import io
from typing import Any

from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    IMPORT_POLICY_VERSION,
    OCCURRENCE_KIND,
)
from finjuice.pipeline.storage.sqlite.exact_import.evidence import PersistSession, utc_now
from finjuice.pipeline.storage.sqlite.exact_import.mapping import ExactWorkbookMappings
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportCommand, ImportPlan
from finjuice.pipeline.storage.sqlite.exact_import.persist_assets import persist_assets
from finjuice.pipeline.storage.sqlite.exact_import.persist_manifest import persist_manifest
from finjuice.pipeline.storage.sqlite.exact_import.persist_overview import persist_overview
from finjuice.pipeline.storage.sqlite.exact_import.persist_transactions import persist_transactions
from finjuice.pipeline.storage.sqlite.exact_import.persist_uncovered import persist_uncovered
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.mutations import MutationContext, MutationOutcome
from finjuice.pipeline.storage.sqlite.objects import SourceArtifact, SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import SourceOccurrenceRecord

JSONValue = Any


def persist_new_import(
    context: MutationContext,
    command: ExactImportCommand,
    mappings: ExactWorkbookMappings,
    plan: ImportPlan,
) -> MutationOutcome:
    """Publish source bytes, then persist occurrence, facts, and the root manifest."""
    artifact = _publish_captured_bytes(context, command)
    occurrence_id = new_entity_id()
    context.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind=OCCURRENCE_KIND,
            original_filename=command.capture.filename,
            imported_at=utc_now(),
            parser_version=IMPORT_POLICY_VERSION,
        )
    )
    session = PersistSession(
        context=context,
        occurrence_id=occurrence_id,
        artifact_id=artifact.artifact_id,
        imported_at=utc_now(),
        collected_at=command.intent.collected_at,
        parser_version=IMPORT_POLICY_VERSION,
    )
    ids = _persist_families(session, command, mappings, plan)
    persist_manifest(
        session,
        intent=command.intent,
        counts=plan.counts,
        ids=ids,
        mapping_issue_codes=plan.mapping_issue_codes,
    )
    return MutationOutcome(
        result=_committed_result(plan, occurrence_id, artifact.artifact_id, ids),
        retained_artifacts=(artifact.artifact_id,),
    )


def _publish_captured_bytes(
    context: MutationContext,
    command: ExactImportCommand,
) -> SourceArtifact:
    store = SourceObjectStore(context.authority.paths)
    artifact = store.publish(io.BytesIO(command.capture.source_bytes))
    context.retain_artifact(artifact.artifact_id)
    if artifact.digest_hex != command.capture.digest_hex:
        raise RuntimeError("Published artifact digest does not match captured bytes.")
    context.register_source_artifact(artifact)
    return artifact


def _persist_families(
    session: PersistSession,
    command: ExactImportCommand,
    mappings: ExactWorkbookMappings,
    plan: ImportPlan,
) -> dict[str, JSONValue]:
    transaction_ids = persist_transactions(session, mappings.transactions, plan.decisions)
    asset_ids = persist_assets(session, mappings.assets, plan.decisions)
    overview_ids = persist_overview(session, mappings.overview)
    uncovered = persist_uncovered(
        session,
        command.capture.evidence,
        plan.claimed_sheets,
        plan.decisions,
        overview_sheet=_mapped_overview_sheet(mappings),
    )
    return {
        "asset_ids": asset_ids,
        "occurrence_id": session.occurrence_id,
        "overview_fact_ids": overview_ids.get("facts", []),
        "overview_projection_ids": overview_ids.get("projections", []),
        "transaction_ids": transaction_ids,
        "uncovered_rows": uncovered,
    }


def _mapped_overview_sheet(mappings: ExactWorkbookMappings) -> str | None:
    if mappings.overview.status != "mapped":
        return None
    return mappings.overview.sheet_name


def _committed_result(
    plan: ImportPlan,
    occurrence_id: str,
    artifact_id: str,
    ids: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    return {
        "artifact_id": artifact_id,
        "completed": True,
        "counts": plan.counts.as_dict(),
        "noop": False,
        "occurrence_id": occurrence_id,
        "transaction_ids": list(ids["transaction_ids"]),
    }
