"""Apply persisted intake decisions through the canonical mutation transaction."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.account_decisions import (
    OwnershipDecision,
    OwnershipShareDecision,
)
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.records import (
    AgentIntakeApplicationRecord,
    AgentIntakeConfirmationRecord,
)

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import (
        MutationContext,
        MutationReceipt,
        MutationRequest,
        MutationService,
    )


def confirm_intake(  # noqa: PLR0913 - Keep caller-supplied mutation preconditions explicit.
    service: MutationService,
    decision: Mapping[str, Any],
    *,
    expected_generation: str,
    expected_revision: int,
    idempotency_key: str,
    confirmed_at: str,
    actor: str = "cli",
) -> MutationReceipt:
    """Apply a detached proposal using explicit preconditions checked again under the lock."""
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationRequest

    if (expected_generation, expected_revision, idempotency_key) != (
        decision["expected_generation"],
        decision["expected_revision"],
        decision["application_key"],
    ):
        raise MutationConflictError("Confirmation identity must match the selected proposal.")
    try:
        timestamp = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Missing timezone.")
    except (ValueError, AttributeError) as error:
        raise MutationValidationError(
            "Confirmation time needs an ISO timestamp with timezone."
        ) from error
    proposal_id = decision["proposal_id"]
    request = MutationRequest(
        command_scope=decision["application_scope"],
        idempotency_key=idempotency_key,
        payload=decision["proposal"],
        expected_generation=expected_generation,
        expected_revision=expected_revision,
        actor=actor,
        confirmation={"proposal_id": proposal_id, "confirmed_at": confirmed_at},
    )
    return service.execute(
        request,
        lambda context: MutationOutcome(
            result=context.apply_intake_decision(proposal_id, request, confirmed_at)
        ),
    )


def apply_intake_decision(
    connection: sqlite3.Connection,
    context: MutationContext,
    proposal_id: str,
    request: MutationRequest,
    confirmed_at: str,
) -> Mapping[str, Any]:
    """Confirm and apply exactly the stored proposal inside its caller's transaction."""
    validate_entity_id(proposal_id)
    row = connection.execute(
        "SELECT p.command_scope, p.idempotency_key, p.expected_generation, "
        "p.expected_revision, p.payload_json, o.occurrence_json "
        "FROM agent_intake_proposals p "
        "JOIN agent_intake_extractions e ON e.extraction_id = p.extraction_id "
        "JOIN agent_intake_occurrences o ON o.occurrence_id = e.occurrence_id "
        "WHERE p.proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Unknown intake proposal.")
    scope, key, generation, revision, payload_json, occurrence_json = row
    payload = json.loads(payload_json)
    if (scope, key, generation, revision, payload) != (
        request.command_scope,
        request.idempotency_key,
        request.expected_generation,
        request.expected_revision,
        dict(request.payload),
    ):
        raise MutationConflictError(
            "Confirmation must retain the stored proposal and preconditions."
        )
    detail = json.loads(occurrence_json)
    if detail.get("uncertainties"):
        raise MutationValidationError("Resolve intake uncertainties in a new proposal first.")
    if connection.execute(
        "SELECT 1 FROM agent_intake_confirmations WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone():
        raise MutationConflictError("Intake proposal already has a decision.")
    result = _apply_domain(context, payload)
    confirmation_id = new_entity_id()
    context.add_intake_confirmation(
        AgentIntakeConfirmationRecord(
            confirmation_id=confirmation_id,
            proposal_id=proposal_id,
            confirmation_state="confirmed",
            actor=request.actor,
            detail={"operation": payload["operation"], "change_kind": payload["change_kind"]},
            confirmed_at=confirmed_at,
        )
    )
    context.add_intake_application(
        AgentIntakeApplicationRecord(
            proposal_id=proposal_id,
            confirmation_id=confirmation_id,
            changeset_id=context.changeset_id,
            applied_at=confirmed_at,
        )
    )
    return {
        "proposal_id": proposal_id,
        "confirmation_id": confirmation_id,
        "change_kind": payload["change_kind"],
        "operation": payload["operation"],
        "applied": dict(result),
    }


def _apply_domain(context: MutationContext, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(payload) != {"change_kind", "operation", "decision"}:
        raise MutationValidationError("Intake proposal needs change_kind, operation and decision.")
    decision = payload["decision"]
    if not isinstance(decision, dict):
        raise MutationValidationError("Intake decision must be an object.")
    operation = payload["operation"]
    kind = payload["change_kind"]
    try:
        if kind == "account_fact" and operation == "account_binding":
            return context.confirm_account_binding(AccountBindingConfirmation(**decision))
        if kind == "account_fact" and operation == "ownership":
            fields = dict(decision)
            shares = tuple(OwnershipShareDecision(**item) for item in fields.pop("shares"))
            return context.confirm_ownership(OwnershipDecision(**fields, shares=shares))
        if kind == "account_fact" and operation == "asset_meaning":
            from finjuice.pipeline.storage.sqlite.asset_meanings import AssetMeaningDecision

            return context.confirm_asset_meaning(AssetMeaningDecision(**decision))
        if kind == "transaction_override" and operation == "manual_transaction":
            from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

            return context.edit_manual_transaction(ManualTransactionEdit(**decision))
        if kind == "recurring_rule" and operation == "rule":
            from finjuice.pipeline.storage.sqlite.intake_rules import apply_rule_decision

            return apply_rule_decision(context, decision)
    except (TypeError, KeyError) as error:
        raise MutationValidationError(
            "Intake decision does not match its operation contract."
        ) from error
    raise MutationValidationError("Unsupported intake operation for this change kind.")
