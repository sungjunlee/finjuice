"""Atomic proposal revision and withdrawal over preserved canonical intake evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.intake_lineage import proposal_target
from finjuice.pipeline.storage.sqlite.intake_queries import intake_decision_view
from finjuice.pipeline.storage.sqlite.intake_submission import (
    IntakeSubmission,
    _json,
    capture_intake,
)
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import AgentIntakeConfirmationRecord

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext, MutationRequest


@dataclass(frozen=True)
class IntakeRevision:
    parent_proposal_id: str
    parent_payload_digest: str
    proposal: Mapping[str, Any]
    evidence: Mapping[str, Any]
    revised_at: str
    uncertainties: tuple[str, ...]
    resolutions: Mapping[str, str]
    extraction: Mapping[str, Any] | list[Any] | None = None


@dataclass(frozen=True)
class IntakeWithdrawal:
    proposal_id: str
    payload_digest: str
    evidence: Mapping[str, Any]
    rejected_at: str


def _validate_evidence(evidence: Mapping[str, Any], timestamp: str) -> None:
    if not isinstance(evidence, Mapping) or not evidence:
        raise MutationValidationError("A decision requires explicit nonempty evidence.")
    _json(evidence)
    try:
        if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise MutationValidationError(
            "Decision time must be an ISO timestamp with timezone."
        ) from exc


def _decision(connection: sqlite3.Connection, proposal_id: str, digest: str) -> dict[str, Any]:
    validate_entity_id(proposal_id)
    decision = next(
        (
            row
            for row in intake_decision_view(connection)["decisions"]
            if row["proposal_id"] == proposal_id
        ),
        None,
    )
    if decision is None or decision["payload_digest"] != digest:
        raise MutationConflictError("Parent proposal identity and payload digest must match.")
    return decision


def _applied_result(
    connection: sqlite3.Connection, parent: Mapping[str, Any]
) -> dict[str, Any] | None:
    if parent["application"] is None:
        return None
    row = connection.execute(
        "SELECT result_json FROM idempotency_requests "
        "WHERE changeset_id = ? AND status = 'committed'",
        (parent["application"]["changeset_id"],),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Applied proposal has no durable receipt.")
    return dict(json.loads(row[0])["result"]["applied"])


def _current_head(
    connection: sqlite3.Connection,
    operation: str,
    decision: Mapping[str, Any],
    applied: Mapping[str, Any] | None,
) -> None:
    specs = {
        "account_binding": (
            "account_source_bindings",
            "binding_id",
            "supersedes_binding_id",
            "binding_id",
        ),
        "ownership": (
            "ownership_assertion_sets",
            "assertion_id",
            "supersedes_assertion_id",
            "assertion_id",
        ),
        "asset_meaning": (
            "asset_meaning_assertions",
            "assertion_id",
            "supersedes_assertion_id",
            "assertion_id",
        ),
    }
    if operation not in specs:
        return
    table, key, previous_key, result_key = specs[operation]
    previous = decision.get(previous_key)
    if previous is None:
        if applied is not None:
            raise MutationValidationError(
                "An applied fact correction requires its current typed head."
            )
        return
    validate_entity_id(previous)
    # Identifiers are selected exclusively from the closed operation table map above.
    cursor = connection.execute(f"SELECT * FROM {table} WHERE {key} = ?", (previous,))
    names = [column[0] for column in cursor.description]
    values = cursor.fetchone()
    if values is None:
        raise MutationConflictError("The requested typed correction head does not exist.")
    head = dict(zip(names, values, strict=True))
    state_filter = " AND confirmation_state = 'confirmed'" if operation == "ownership" else ""
    if connection.execute(
        f"SELECT 1 FROM {table} WHERE {previous_key} = ?{state_filter}", (previous,)
    ).fetchone():
        raise MutationConflictError("The requested typed head has already been superseded.")
    target_fields = {
        "account_binding": ("source_namespace", "external_key"),
        "ownership": ("account_id",),
        "asset_meaning": ("source_entity_id", "account_id"),
    }[operation]
    if any(head[field] != decision[field] for field in target_fields):
        raise MutationConflictError("The typed head belongs to a different correction target.")
    if applied is not None:
        ancestor = previous
        seen = set()
        while ancestor != applied[result_key]:
            if ancestor is None or ancestor in seen:
                raise MutationConflictError("The current head is outside the applied fact lineage.")
            seen.add(ancestor)
            row = connection.execute(
                f"SELECT {previous_key} FROM {table} WHERE {key} = ?", (ancestor,)
            ).fetchone()
            ancestor = row[0] if row else None


def _validate_revision(
    connection: sqlite3.Connection,
    context: MutationContext,
    parent: Mapping[str, Any],
    revision: IntakeRevision,
) -> None:
    _validate_evidence(revision.evidence, revision.revised_at)
    if proposal_target(parent["proposal"]) != proposal_target(revision.proposal):
        raise MutationValidationError("Revision must retain its change type, operation and target.")
    removed = set(parent["uncertainties"]) - set(revision.uncertainties)
    if set(revision.resolutions) != removed or any(
        not isinstance(reason, str) or not reason.strip()
        for reason in revision.resolutions.values()
    ):
        raise MutationValidationError(
            "Each resolved uncertainty needs explicit resolution evidence."
        )
    if parent.get("successor_proposal_ids"):
        raise MutationConflictError(
            "Revise the latest successor instead of branching an old proposal."
        )
    if parent["application"] is None and parent["confirmations"]:
        raise MutationConflictError("A withdrawn proposal cannot be revised; submit new evidence.")
    applied = _applied_result(connection, parent)
    if applied is not None and revision.proposal["operation"] == "asset_observation":
        raise MutationValidationError(
            "Applied observation values are immutable; "
            "submit an asset_meaning correction for its source identity."
        )
    _current_head(
        connection, revision.proposal["operation"], revision.proposal["decision"], applied
    )
    if applied and revision.proposal["operation"] == "manual_transaction":
        # Applied receipts contain the stable resolved transaction, not merely its old alias.
        identifier = revision.proposal["decision"]["identifier"]
        if context.intake_transaction_target(identifier) != applied["transaction_id"]:
            raise MutationValidationError(
                "Applied transaction corrections require the same stable transaction UUID."
            )


def _original_bytes(context: MutationContext, parent: Mapping[str, Any]) -> bytes:
    store = SourceObjectStore(context.authority.paths)
    artifact = store.verify(parent["source_artifact_id"])
    content = read_regular_bytes(context.authority.paths.object_path(artifact.digest_hex))
    if (
        len(content) != artifact.byte_length
        or hashlib.sha256(content).hexdigest() != artifact.digest_hex
    ):
        raise MutationValidationError(
            "Retained source bytes no longer match their verified identity."
        )
    return content


def revise_intake(
    connection: sqlite3.Connection,
    context: MutationContext,
    revision: IntakeRevision,
    request: MutationRequest,
) -> dict[str, Any]:
    """Create a successor and retire an unapplied parent in one canonical transaction."""
    parent = _decision(connection, revision.parent_proposal_id, revision.parent_payload_digest)
    _validate_revision(connection, context, parent, revision)
    if request.idempotency_key == parent["application_key"]:
        raise MutationValidationError(
            "Revision requires a new key, not the parent application key."
        )
    content = _original_bytes(context, parent)
    identity = hashlib.sha256(
        _json(["revision", revision.parent_proposal_id, request.idempotency_key]).encode()
    ).hexdigest()
    lineage = {
        "parent_proposal_id": parent["proposal_id"],
        "parent_payload_digest": parent["payload_digest"],
        "parent_extraction_id": parent["extraction_id"],
        "evidence": dict(revision.evidence),
        "resolved_uncertainties": dict(revision.resolutions),
        "parent_application_changeset_id": parent["application"]["changeset_id"]
        if parent["application"]
        else None,
    }
    submission = IntakeSubmission(
        source_kind=parent["occurrence"]["source_kind"],
        content=content,
        media_type=parent["occurrence"]["media_type"],
        channel="cli.revision",
        received_at=revision.revised_at,
        extractor=parent["extractor"] if revision.extraction is None else "operator.revision.v1",
        extraction=parent["extraction"] if revision.extraction is None else revision.extraction,
        proposal_scope=parent["application_scope"],
        proposal=revision.proposal,
        policy_version=parent["policy_version"],
        idempotency_key=request.idempotency_key,
        expected_generation=request.expected_generation,
        expected_revision=request.expected_revision,
        actor=request.actor,
        uncertainties=revision.uncertainties,
    )
    outcome = capture_intake(context, submission, identity, "intake.apply." + identity, lineage)
    for artifact_id in outcome.retained_artifacts:
        context.retain_artifact(artifact_id)
    result = dict(outcome.result)
    if parent["application"] is None and not parent["confirmations"]:
        context.add_intake_confirmation(
            AgentIntakeConfirmationRecord(
                new_entity_id(),
                parent["proposal_id"],
                "rejected",
                request.actor,
                {
                    "action": "superseded",
                    "successor_proposal_id": result["proposal_id"],
                    "evidence": dict(revision.evidence),
                },
                revision.revised_at,
            )
        )
    return {
        **result,
        "parent_proposal_id": parent["proposal_id"],
        "parent_status": "applied" if parent["application"] else "revised",
    }


def withdraw_intake(
    connection: sqlite3.Connection,
    context: MutationContext,
    command: IntakeWithdrawal,
    request: MutationRequest,
) -> dict[str, Any]:
    """Reject a not-yet-applied proposal without undoing any applied domain mutation."""
    _validate_evidence(command.evidence, command.rejected_at)
    parent = _decision(connection, command.proposal_id, command.payload_digest)
    if parent["application"] is not None:
        raise MutationConflictError("Applied proposals require typed correction, not withdrawal.")
    if parent["confirmations"] or parent.get("successor_proposal_ids"):
        raise MutationConflictError("The proposal already has a decision or successor.")
    confirmation_id = new_entity_id()
    context.add_intake_confirmation(
        AgentIntakeConfirmationRecord(
            confirmation_id,
            command.proposal_id,
            "rejected",
            request.actor,
            {"action": "withdrawn", "evidence": dict(command.evidence)},
            command.rejected_at,
        )
    )
    return {
        "proposal_id": command.proposal_id,
        "confirmation_id": confirmation_id,
        "status": "rejected",
    }
