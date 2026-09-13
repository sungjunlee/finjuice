"""Submit XLSX, description, and screenshot values through one intake contract."""

from __future__ import annotations

from dataclasses import replace

from finjuice.pipeline.agent.apply import (
    amend_changeset,
    confirm_account_mapping,
    confirm_proposal,
    confirmed_account_facts,
    recurring_rules,
    withdraw_changeset,
)
from finjuice.pipeline.agent.keys import (
    derived_submit_key,
    description_digest,
    extraction_digest,
    intake_entity_id,
    source_digest,
)
from finjuice.pipeline.agent.models import (
    CHANGE_KINDS,
    SOURCE_KINDS,
    AmendRequest,
    ApplyReceipt,
    ChangeKindLockedError,
    ChangesetRecord,
    ConfirmRequest,
    EvidenceRecord,
    ExtractionRecord,
    IdempotencyConflictError,
    IntakeError,
    IntakeInput,
    IntakeReceipt,
    IntakeStore,
    MappingRequest,
    OperatorView,
    ProposalRecord,
    WithdrawRequest,
    stored_int,
    stored_text,
)
from finjuice.pipeline.agent.render import operator_payload, render_operator_view


def submit_intake(
    store: IntakeStore,
    payload: IntakeInput,
    *,
    idempotency_key: str | None = None,
) -> IntakeReceipt:
    """Record original, extraction, and interpretation without applying them."""
    _validate_input(payload)
    key = idempotency_key or derived_submit_key(payload)
    payload_digest = derived_submit_key(payload)
    replayed = _replay_submit(store, key, payload_digest)
    if replayed is not None:
        return replayed
    digest = source_digest(payload)
    evidence = _upsert_evidence(store, payload, digest)
    extraction = _upsert_extraction(store, evidence.evidence_id, payload)
    proposal = _upsert_proposal(store, evidence, extraction, payload)
    receipt = IntakeReceipt(
        evidence_id=evidence.evidence_id,
        extraction_id=extraction.extraction_id,
        proposal_id=proposal.proposal_id,
        idempotency_key=key,
        source_digest=digest,
        replayed=False,
        revision=store.revision,
    )
    store.receipts[("submit", key)] = {
        "payload_digest": payload_digest,
        "evidence_id": receipt.evidence_id,
        "extraction_id": receipt.extraction_id,
        "proposal_id": receipt.proposal_id,
        "source_digest": digest,
        "revision": receipt.revision,
    }
    return receipt


def import_xlsx_source(store: IntakeStore, payload: IntakeInput) -> IntakeReceipt:
    """Ingest an XLSX source without clearing confirmed account facts."""
    if payload.source_kind != "xlsx":
        raise IntakeError("XLSX import requires source_kind='xlsx'.")
    preserved = tuple(item.changeset_id for item in confirmed_account_facts(store))
    receipt = submit_intake(store, payload)
    if not receipt.replayed:
        store.revision += 1
        receipt = replace(receipt, revision=store.revision)
    _assert_account_facts_preserved(store, preserved)
    return receipt


class IntakeSession:
    """Stateful M1 intake session for Hermes confirmation and correction."""

    def __init__(self) -> None:
        self._store = IntakeStore()

    @property
    def revision(self) -> int:
        """Return the current expected revision."""
        return self._store.revision

    @property
    def store(self) -> IntakeStore:
        """Return the underlying store for read-only inspection in tests."""
        return self._store

    def submit(self, payload: IntakeInput, *, idempotency_key: str | None = None) -> IntakeReceipt:
        """Submit one common-contract intake payload."""
        return submit_intake(self._store, payload, idempotency_key=idempotency_key)

    def confirm_mapping(self, request: MappingRequest) -> ProposalRecord:
        """Resolve uncertain account mapping before confirmation."""
        return confirm_account_mapping(self._store, request)

    def confirm(self, request: ConfirmRequest) -> ApplyReceipt:
        """Confirm a pending proposal into a tracked changeset."""
        return confirm_proposal(self._store, request)

    def withdraw(self, request: WithdrawRequest) -> ApplyReceipt:
        """Withdraw a previously applied changeset."""
        return withdraw_changeset(self._store, request)

    def amend(self, request: AmendRequest) -> ApplyReceipt:
        """Amend a changeset without converting its change kind."""
        return amend_changeset(self._store, request)

    def import_xlsx(self, payload: IntakeInput) -> IntakeReceipt:
        """Apply a later XLSX import while keeping confirmed account facts."""
        return import_xlsx_source(self._store, payload)

    def confirmed_account_facts(self) -> tuple[ChangesetRecord, ...]:
        """Return live confirmed account facts."""
        return confirmed_account_facts(self._store)

    def recurring_rules(self) -> tuple[ChangesetRecord, ...]:
        """Return live recurring rules."""
        return recurring_rules(self._store)

    def operator_view(self) -> OperatorView:
        """Return human/JSON results containing only pending operator decisions."""
        payload = operator_payload(self._store)
        return OperatorView(payload=payload, human=render_operator_view(payload))


def _validate_input(payload: IntakeInput) -> None:
    if payload.source_kind not in SOURCE_KINDS:
        raise IntakeError("Unknown source_kind.")
    if payload.interpretation.change_kind not in CHANGE_KINDS:
        raise IntakeError("Unknown change_kind.")
    _validate_source_presence(payload)
    _validate_change_kind(payload)


def _validate_source_presence(payload: IntakeInput) -> None:
    if payload.source_kind == "screenshot" and not payload.image_bytes:
        raise IntakeError("Screenshot intake requires image bytes.")
    if payload.source_kind == "description" and not payload.description:
        raise IntakeError("Description intake requires description text.")
    if payload.source_kind == "xlsx" and not payload.xlsx_bytes:
        raise IntakeError("XLSX intake requires workbook bytes.")


def _validate_change_kind(payload: IntakeInput) -> None:
    draft = payload.interpretation
    if draft.change_kind == "transaction_override":
        if draft.impact.applies_recurring:
            raise ChangeKindLockedError("A one-time override cannot apply as a recurring rule.")
        if not draft.target_id:
            raise IntakeError("A one-time override requires a target transaction id.")
    if draft.change_kind == "recurring_rule" and not draft.impact.applies_recurring:
        raise IntakeError("A recurring rule must set applies_recurring.")
    if draft.change_kind == "account_fact" and draft.impact.applies_recurring:
        raise ChangeKindLockedError("An account fact cannot apply as a recurring rule.")


def _upsert_evidence(store: IntakeStore, payload: IntakeInput, digest: str) -> EvidenceRecord:
    evidence_id = store.source_digests.get(digest) or intake_entity_id(f"evidence/{digest}")
    existing = store.evidence.get(evidence_id)
    if existing is not None:
        return existing
    record = EvidenceRecord(
        evidence_id=evidence_id,
        source_kind=payload.source_kind,
        source_digest=digest,
        description_digest=description_digest(payload.description),
        original_description=payload.description,
        has_image=bool(payload.image_bytes),
        has_xlsx=bool(payload.xlsx_bytes),
        created_revision=store.revision,
    )
    store.evidence[evidence_id] = record
    store.source_digests[digest] = evidence_id
    return record


def _upsert_extraction(
    store: IntakeStore, evidence_id: str, payload: IntakeInput
) -> ExtractionRecord:
    existing = store.extractions.get(evidence_id)
    fields = tuple(sorted(payload.extracted.items()))
    digest = extraction_digest(payload.extracted)
    if existing is not None and _proposal_locked(store, evidence_id):
        if existing.extraction_digest != digest:
            raise IdempotencyConflictError("Confirmed extraction cannot be replaced.")
        return existing
    record = ExtractionRecord(
        extraction_id=intake_entity_id(f"extraction/{evidence_id}"),
        evidence_id=evidence_id,
        extracted_fields=fields,
        extraction_digest=digest,
    )
    store.extractions[evidence_id] = record
    return record


def _upsert_proposal(
    store: IntakeStore,
    evidence: EvidenceRecord,
    extraction: ExtractionRecord,
    payload: IntakeInput,
) -> ProposalRecord:
    change_kind = payload.interpretation.change_kind
    proposal_id = intake_entity_id(f"proposal/{evidence.evidence_id}/{change_kind}")
    existing = store.proposals.get(proposal_id)
    if existing is not None and existing.status != "pending":
        if _same_proposal(existing, extraction, payload):
            return existing
        raise IdempotencyConflictError("Confirmed proposal lineage cannot be replaced.")
    record = ProposalRecord(
        proposal_id=proposal_id,
        evidence_id=evidence.evidence_id,
        extraction_id=extraction.extraction_id,
        change_kind=change_kind,
        mapping=payload.interpretation.account_mapping,
        impact=payload.interpretation.impact,
        target_id=payload.interpretation.target_id,
        status="pending",
        created_revision=store.revision,
    )
    store.proposals[proposal_id] = record
    return record


def _same_proposal(
    existing: ProposalRecord,
    extraction: ExtractionRecord,
    payload: IntakeInput,
) -> bool:
    draft = payload.interpretation
    return (
        existing.extraction_id == extraction.extraction_id
        and existing.change_kind == draft.change_kind
        and existing.mapping == draft.account_mapping
        and existing.impact == draft.impact
        and existing.target_id == draft.target_id
    )


def _proposal_locked(store: IntakeStore, evidence_id: str) -> bool:
    return any(
        item.evidence_id == evidence_id and item.status != "pending"
        for item in store.proposals.values()
    )


def _replay_submit(store: IntakeStore, key: str, payload_digest: str) -> IntakeReceipt | None:
    stored = store.receipts.get(("submit", key))
    if stored is None:
        return None
    if stored.get("payload_digest") != payload_digest:
        raise IdempotencyConflictError("Idempotency key is bound to a different submit payload.")
    return IntakeReceipt(
        evidence_id=stored_text(stored, "evidence_id"),
        extraction_id=stored_text(stored, "extraction_id"),
        proposal_id=stored_text(stored, "proposal_id"),
        idempotency_key=key,
        source_digest=stored_text(stored, "source_digest"),
        replayed=True,
        revision=stored_int(stored, "revision"),
    )


def _assert_account_facts_preserved(store: IntakeStore, preserved: tuple[str, ...]) -> None:
    remaining = {item.changeset_id for item in confirmed_account_facts(store)}
    if any(changeset_id not in remaining for changeset_id in preserved):
        raise IntakeError("XLSX import must not drop confirmed account facts.")
