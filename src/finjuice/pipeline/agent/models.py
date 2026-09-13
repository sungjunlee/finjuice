"""Structured agent-intake records for evidence, proposals, and changesets.

Layers stay distinct: original evidence, extraction, interpretation proposal,
user confirmation, and applied changeset. Change kinds stay distinct so a
one-time override cannot silently become a recurring rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

SourceKind = Literal["xlsx", "description", "screenshot"]
ChangeKind = Literal["transaction_override", "recurring_rule", "account_fact"]
MappingStatus = Literal["certain", "uncertain", "unmapped"]
ProposalStatus = Literal["pending", "confirmed", "withdrawn"]
ChangesetStatus = Literal["confirmed", "withdrawn", "amended"]
DecisionKind = Literal[
    "uncertain_account_mapping",
    "stale_proposal",
    "awaiting_confirmation",
]

SOURCE_KINDS = frozenset({"xlsx", "description", "screenshot"})
CHANGE_KINDS = frozenset({"transaction_override", "recurring_rule", "account_fact"})
MAPPING_STATUSES = frozenset({"certain", "uncertain", "unmapped"})


def _default_interpretation() -> InterpretationDraft:
    return InterpretationDraft(change_kind="account_fact")


class IntakeError(ValueError):
    """Base error for agent intake."""


class IdempotencyConflictError(IntakeError):
    """Raised when an idempotency key is reused with a different payload."""


class StaleRevisionError(IntakeError):
    """Raised when a write uses an outdated expected revision."""


class UncertainMappingError(IntakeError):
    """Raised when confirmation is attempted before account mapping is certain."""


class ChangeKindLockedError(IntakeError):
    """Raised when a one-time override is asked to behave as a recurring rule."""


class UnknownRecordError(IntakeError):
    """Raised when a referenced intake record does not exist."""


@dataclass(frozen=True)
class AccountMapping:
    """Interpreted account mapping that may stay uncertain until confirmed."""

    status: MappingStatus = "uncertain"
    candidate_account_id: str | None = None
    account_kind: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class ImpactScope:
    """Declared impact of a proposed change. Recurring apply is explicit."""

    account_ids: tuple[str, ...] = ()
    transaction_ids: tuple[str, ...] = ()
    applies_recurring: bool = False


@dataclass(frozen=True)
class InterpretationDraft:
    """Operator-facing interpretation distinct from raw extraction."""

    change_kind: ChangeKind
    account_mapping: AccountMapping = field(default_factory=AccountMapping)
    impact: ImpactScope = field(default_factory=ImpactScope)
    target_id: str | None = None


@dataclass(frozen=True)
class IntakeInput:
    """Common input contract for XLSX, descriptions, and screenshot values."""

    source_kind: SourceKind
    description: str = ""
    image_bytes: bytes = b""
    xlsx_bytes: bytes = b""
    extracted: Mapping[str, str] = field(default_factory=dict)
    interpretation: InterpretationDraft = field(default_factory=_default_interpretation)


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable original evidence. Source bytes/text are preserved here."""

    evidence_id: str
    source_kind: SourceKind
    source_digest: str
    description_digest: str
    original_description: str
    has_image: bool
    has_xlsx: bool
    created_revision: int


@dataclass(frozen=True)
class ExtractionRecord:
    """Structured extraction distinct from original bytes and interpretation."""

    extraction_id: str
    evidence_id: str
    extracted_fields: tuple[tuple[str, str], ...]
    extraction_digest: str


@dataclass(frozen=True)
class ProposalRecord:
    """Interpretation proposal waiting for mapping certainty and confirmation."""

    proposal_id: str
    evidence_id: str
    extraction_id: str
    change_kind: ChangeKind
    mapping: AccountMapping
    impact: ImpactScope
    target_id: str | None
    status: ProposalStatus
    created_revision: int


@dataclass(frozen=True)
class ConfirmationRecord:
    """User confirmation distinct from the proposal and applied changeset."""

    confirmation_id: str
    proposal_id: str
    changeset_id: str
    expected_revision: int
    decided_at_revision: int


@dataclass(frozen=True)
class ChangesetRecord:
    """Applied change that can be tracked, amended, or withdrawn."""

    changeset_id: str
    proposal_id: str
    confirmation_id: str
    change_kind: ChangeKind
    mapping: AccountMapping
    impact: ImpactScope
    target_id: str | None
    status: ChangesetStatus
    supersedes_changeset_id: str | None
    applied_revision: int


@dataclass(frozen=True)
class IntakeReceipt:
    """Idempotent submit result for Hermes tool retries."""

    evidence_id: str
    extraction_id: str
    proposal_id: str
    idempotency_key: str
    source_digest: str
    replayed: bool
    revision: int


@dataclass(frozen=True)
class ApplyReceipt:
    """Idempotent confirm/withdraw/amend result."""

    changeset_id: str
    proposal_id: str
    idempotency_key: str
    replayed: bool
    revision: int
    status: ChangesetStatus


@dataclass(frozen=True)
class ConfirmRequest:
    """Confirm a pending proposal against an expected revision."""

    proposal_id: str
    expected_revision: int
    idempotency_key: str | None = None


@dataclass(frozen=True)
class WithdrawRequest:
    """Withdraw an applied changeset against an expected revision."""

    changeset_id: str
    expected_revision: int
    idempotency_key: str | None = None


@dataclass(frozen=True)
class AmendRequest:
    """Amend an applied changeset without changing its change kind."""

    changeset_id: str
    expected_revision: int
    mapping: AccountMapping | None = None
    impact: ImpactScope | None = None
    target_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class MappingRequest:
    """Resolve an uncertain account mapping without applying the changeset."""

    proposal_id: str
    account_id: str
    account_kind: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class OperatorDecision:
    """One operator action required before a proposal may be confirmed."""

    kind: DecisionKind
    proposal_id: str
    evidence_id: str
    change_kind: ChangeKind
    source_digest: str
    created_revision: int
    current_revision: int

    def to_dict(self) -> dict[str, str | int]:
        """Return the JSON object for one pending decision."""
        return {
            "kind": self.kind,
            "proposal_id": self.proposal_id,
            "evidence_id": self.evidence_id,
            "change_kind": self.change_kind,
            "source_digest": self.source_digest,
            "created_revision": self.created_revision,
            "current_revision": self.current_revision,
        }


@dataclass(frozen=True)
class OperatorView:
    """Human/JSON operator surface that lists only pending decisions."""

    payload: dict[str, Any]
    human: str


@dataclass
class IntakeStore:
    """In-memory intake authority used by the M1 confirmation slice."""

    revision: int = 0
    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    extractions: dict[str, ExtractionRecord] = field(default_factory=dict)
    proposals: dict[str, ProposalRecord] = field(default_factory=dict)
    confirmations: dict[str, ConfirmationRecord] = field(default_factory=dict)
    changesets: dict[str, ChangesetRecord] = field(default_factory=dict)
    receipts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    source_digests: dict[str, str] = field(default_factory=dict)


def stored_text(stored: Mapping[str, object], key: str) -> str:
    """Return a string field from an idempotency receipt."""
    value = stored[key]
    if not isinstance(value, str):
        raise IntakeError("Stored receipt is invalid.")
    return value


def stored_int(stored: Mapping[str, object], key: str) -> int:
    """Return an integer field from an idempotency receipt."""
    value = stored[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntakeError("Stored receipt is invalid.")
    return value


def stored_changeset_status(stored: Mapping[str, object]) -> ChangesetStatus:
    """Return a changeset status from an idempotency receipt."""
    value = stored["status"]
    if value == "confirmed":
        return "confirmed"
    if value == "withdrawn":
        return "withdrawn"
    if value == "amended":
        return "amended"
    raise IntakeError("Stored receipt is invalid.")
