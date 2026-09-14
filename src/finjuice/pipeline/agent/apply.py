"""Confirm, withdraw, amend, and query applied intake changesets."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from finjuice.pipeline.agent.keys import json_digest
from finjuice.pipeline.agent.models import (
    AccountMapping,
    AmendRequest,
    ApplyReceipt,
    ChangesetRecord,
    ConfirmationRecord,
    ConfirmRequest,
    IdempotencyConflictError,
    IntakeError,
    IntakeStore,
    MappingRequest,
    ProposalRecord,
    StaleRevisionError,
    UncertainMappingError,
    UnknownRecordError,
    WithdrawRequest,
    stored_changeset_status,
    stored_int,
    stored_text,
)


def confirm_account_mapping(store: IntakeStore, request: MappingRequest) -> ProposalRecord:
    """Make a pending proposal's account mapping certain without applying it."""
    proposal = _pending_proposal(store, request.proposal_id)
    mapping = AccountMapping(
        status="certain",
        candidate_account_id=request.account_id,
        account_kind=request.account_kind or proposal.mapping.account_kind,
        label=request.label or proposal.mapping.label,
    )
    impact = proposal.impact
    if request.account_id and request.account_id not in impact.account_ids:
        impact = replace(impact, account_ids=impact.account_ids + (request.account_id,))
    updated = replace(proposal, mapping=mapping, impact=impact)
    store.proposals[proposal.proposal_id] = updated
    return updated


def confirm_proposal(store: IntakeStore, request: ConfirmRequest) -> ApplyReceipt:
    """Apply a pending proposal as a changeset when mapping and revision match."""
    key = request.idempotency_key or json_digest(
        {
            "scope": "confirm",
            "proposal_id": request.proposal_id,
            "expected_revision": request.expected_revision,
        }
    )
    replayed = _replay_apply(store, "confirm", key, request.proposal_id)
    if replayed is not None:
        return replayed
    proposal = _pending_proposal(store, request.proposal_id)
    _reject_uncertain_or_stale(store, proposal, request.expected_revision)
    confirmation_id = str(uuid4())
    changeset_id = str(uuid4())
    applied_revision = store.revision + 1
    confirmation = ConfirmationRecord(
        confirmation_id=confirmation_id,
        proposal_id=proposal.proposal_id,
        changeset_id=changeset_id,
        expected_revision=request.expected_revision,
        decided_at_revision=applied_revision,
    )
    changeset = ChangesetRecord(
        changeset_id=changeset_id,
        proposal_id=proposal.proposal_id,
        confirmation_id=confirmation_id,
        change_kind=proposal.change_kind,
        mapping=proposal.mapping,
        impact=proposal.impact,
        target_id=proposal.target_id,
        status="confirmed",
        supersedes_changeset_id=None,
        applied_revision=applied_revision,
    )
    store.confirmations[confirmation_id] = confirmation
    store.changesets[changeset_id] = changeset
    store.proposals[proposal.proposal_id] = replace(proposal, status="confirmed")
    store.revision = applied_revision
    receipt = ApplyReceipt(
        changeset_id=changeset_id,
        proposal_id=proposal.proposal_id,
        idempotency_key=key,
        replayed=False,
        revision=store.revision,
        status="confirmed",
    )
    _store_apply_receipt(store, "confirm", key, receipt, proposal.proposal_id)
    return receipt


def withdraw_changeset(store: IntakeStore, request: WithdrawRequest) -> ApplyReceipt:
    """Withdraw an applied changeset and keep the correction history."""
    key = request.idempotency_key or json_digest(
        {
            "scope": "withdraw",
            "changeset_id": request.changeset_id,
            "expected_revision": request.expected_revision,
        }
    )
    replayed = _replay_apply(store, "withdraw", key, request.changeset_id)
    if replayed is not None:
        return replayed
    changeset = _writable_changeset(store, request.changeset_id, request.expected_revision)
    store.changesets[changeset.changeset_id] = replace(changeset, status="withdrawn")
    store.revision += 1
    receipt = ApplyReceipt(
        changeset_id=changeset.changeset_id,
        proposal_id=changeset.proposal_id,
        idempotency_key=key,
        replayed=False,
        revision=store.revision,
        status="withdrawn",
    )
    _store_apply_receipt(store, "withdraw", key, receipt, changeset.changeset_id)
    return receipt


def amend_changeset(store: IntakeStore, request: AmendRequest) -> ApplyReceipt:
    """Replace an applied changeset while locking its original change kind."""
    key = request.idempotency_key or json_digest(
        {
            "scope": "amend",
            "changeset_id": request.changeset_id,
            "expected_revision": request.expected_revision,
            "target_id": request.target_id,
        }
    )
    replayed = _replay_apply(store, "amend", key, request.changeset_id)
    if replayed is not None:
        return replayed
    current = _writable_changeset(store, request.changeset_id, request.expected_revision)
    successor_id = str(uuid4())
    confirmation_id = str(uuid4())
    applied_revision = store.revision + 1
    successor = ChangesetRecord(
        changeset_id=successor_id,
        proposal_id=current.proposal_id,
        confirmation_id=confirmation_id,
        change_kind=current.change_kind,
        mapping=request.mapping or current.mapping,
        impact=request.impact or current.impact,
        target_id=current.target_id if request.target_id is None else request.target_id,
        status="confirmed",
        supersedes_changeset_id=current.changeset_id,
        applied_revision=applied_revision,
    )
    confirmation = ConfirmationRecord(
        confirmation_id=confirmation_id,
        proposal_id=current.proposal_id,
        changeset_id=successor_id,
        expected_revision=request.expected_revision,
        decided_at_revision=applied_revision,
    )
    store.changesets[current.changeset_id] = replace(current, status="amended")
    store.changesets[successor_id] = successor
    store.confirmations[confirmation_id] = confirmation
    store.revision = applied_revision
    receipt = ApplyReceipt(
        changeset_id=successor_id,
        proposal_id=current.proposal_id,
        idempotency_key=key,
        replayed=False,
        revision=store.revision,
        status="amended",
    )
    _store_apply_receipt(store, "amend", key, receipt, current.changeset_id)
    return receipt


def confirmed_account_facts(store: IntakeStore) -> tuple[ChangesetRecord, ...]:
    """Return live confirmed account facts that later XLSX imports must keep."""
    return _live_changesets(store, "account_fact")


def recurring_rules(store: IntakeStore) -> tuple[ChangesetRecord, ...]:
    """Return live recurring-rule changesets."""
    return _live_changesets(store, "recurring_rule")


def _live_changesets(store: IntakeStore, change_kind: str) -> tuple[ChangesetRecord, ...]:
    superseded = {
        item.supersedes_changeset_id
        for item in store.changesets.values()
        if item.supersedes_changeset_id is not None
    }
    live = [
        item
        for item in store.changesets.values()
        if item.change_kind == change_kind
        and item.status == "confirmed"
        and item.changeset_id not in superseded
    ]
    live.sort(key=lambda item: item.changeset_id)
    return tuple(live)


def _pending_proposal(store: IntakeStore, proposal_id: str) -> ProposalRecord:
    proposal = store.proposals.get(proposal_id)
    if proposal is None:
        raise UnknownRecordError("Unknown proposal.")
    if proposal.status != "pending":
        raise IntakeError(f"Proposal is {proposal.status}, not pending.")
    return proposal


def _writable_changeset(
    store: IntakeStore, changeset_id: str, expected_revision: int
) -> ChangesetRecord:
    changeset = store.changesets.get(changeset_id)
    if changeset is None:
        raise UnknownRecordError("Unknown changeset.")
    if changeset.status != "confirmed":
        raise UnknownRecordError("Changeset is not active.")
    _require_revision(store, expected_revision)
    return changeset


def _reject_uncertain_or_stale(
    store: IntakeStore, proposal: ProposalRecord, expected_revision: int
) -> None:
    if proposal.mapping.status != "certain":
        raise UncertainMappingError("Uncertain account mapping must be resolved before confirm.")
    _require_revision(store, expected_revision)


def _require_revision(store: IntakeStore, expected_revision: int) -> None:
    if expected_revision != store.revision:
        raise StaleRevisionError("expected_revision does not match the current intake revision.")


def _replay_apply(store: IntakeStore, scope: str, key: str, record_id: str) -> ApplyReceipt | None:
    stored = store.receipts.get((scope, key))
    if stored is None:
        return None
    if stored.get("record_id") != record_id:
        raise IdempotencyConflictError("Idempotency key is bound to a different record.")
    return ApplyReceipt(
        changeset_id=stored_text(stored, "changeset_id"),
        proposal_id=stored_text(stored, "proposal_id"),
        idempotency_key=key,
        replayed=True,
        revision=stored_int(stored, "revision"),
        status=stored_changeset_status(stored),
    )


def _store_apply_receipt(
    store: IntakeStore,
    scope: str,
    key: str,
    receipt: ApplyReceipt,
    record_id: str,
) -> None:
    store.receipts[(scope, key)] = {
        "record_id": record_id,
        "changeset_id": receipt.changeset_id,
        "proposal_id": receipt.proposal_id,
        "revision": receipt.revision,
        "status": receipt.status,
        "payload": receipt.idempotency_key,
    }
