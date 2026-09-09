"""Typed preservation records accepted by the isolated repository builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

EntityKind = Literal[
    "source_occurrence",
    "party",
    "account",
    "resource",
    "observation",
    "config_revision",
    "transaction",
    "overview_fact",
    "overview_balance",
    "overview_cashflow",
    "overview_insurance",
    "overview_investment",
    "overview_loan",
    "asset_snapshot",
]


@dataclass(frozen=True)
class SourceOccurrenceRecord:
    """One import/capture occurrence of immutable source bytes."""

    occurrence_id: str
    artifact_id: str
    occurrence_kind: str
    original_filename: str | None = None
    imported_at: str | None = None
    parser_version: str | None = None
    source_schema_version: str | None = None
    legacy_path: str | None = None


@dataclass(frozen=True)
class ProvenanceRecord:
    """Source coordinate and deterministic locator for one preserved record."""

    provenance_id: str
    occurrence_id: str
    source_coordinate: Mapping[str, Any]
    legacy_locator: Mapping[str, Any]
    parser_version: str | None = None
    source_schema_version: str | None = None


@dataclass(frozen=True)
class PreservationIssueRecord:
    """One structured reason typed preservation could not be completed."""

    provenance_id: str
    issue_kind: str
    detail: Mapping[str, Any]
    field_name: str | None = None
    lexical_value: str | None = None
    issue_id: str | None = None


@dataclass(frozen=True)
class LegacyIdentifierRecord:
    """One captured legacy identifier mapping."""

    entity_id: str
    identifier_kind: str
    identifier_value: str
    capture_manifest_digest: str
    provenance_id: str | None = None
    mapping_id: str | None = None


@dataclass(frozen=True)
class MigrationIdentityRecord:
    """Frozen inputs that deterministically produced one migrated entity ID."""

    entity_id: str
    capture_manifest_digest: str
    record_kind: EntityKind
    legacy_locator: Mapping[str, Any]


@dataclass(frozen=True)
class PartyRecord:
    """Stable party identity without inferred household semantics."""

    party_id: str
    party_kind: Literal["unknown", "person", "organization", "household"] = "unknown"
    display_name: str | None = None


@dataclass(frozen=True)
class AccountRecord:
    """Stable account identity with explicit unknown ownership."""

    account_id: str
    account_kind: str
    display_name: str | None = None
    ownership_state: Literal["unknown", "asserted"] = "unknown"
    owner_party_id: str | None = None


@dataclass(frozen=True)
class ResourceRecord:
    """Stable resource or instrument identity."""

    resource_id: str
    resource_kind: str
    display_name: str | None = None


@dataclass(frozen=True)
class ObservationRecord:
    """A source-backed observation with explicit temporal and scope states."""

    observation_id: str
    occurrence_id: str
    observed_at: str | None
    effective_at: str | None
    collected_at: str | None
    scope_state: Literal["complete", "partial", "unknown"]
    confirmation_state: Literal["unconfirmed", "confirmed", "rejected"] = "unconfirmed"
    supersedes_observation_id: str | None = None


@dataclass(frozen=True)
class ConfigRevisionRecord:
    """Immutable source-backed rules/goals or other configuration revision."""

    revision_id: str
    config_kind: Literal["rules", "goals", "assets", "scenarios", "schema", "other"]
    artifact_id: str
    occurrence_id: str
    parsed_status: Literal["parsed", "invalid", "opaque"]
    parser_version: str | None = None
    canonical_payload: Mapping[str, Any] | list[Any] | None = None


@dataclass(frozen=True)
class TransactionRecord:
    """Meaning-preserving typed transaction state for one legacy occurrence."""

    transaction_id: str
    observation_id: str
    provenance_id: str
    account_id: str
    amount_value_id: str
    date_raw: str
    time_raw: str
    datetime_raw: str
    type_raw: str | None
    type_norm: str
    account_text: str
    major_raw: str | None = None
    minor_raw: str | None = None
    merchant_raw: str | None = None
    memo_raw: str | None = None
    notes_manual: str | None = None
    counterparty: str | None = None
    category_rule: str | None = None
    category_manual: str | None = None
    category_final: str | None = None
    tags_rule_json: str = "[]"
    tags_ai_json: str = "[]"
    tags_manual_json: str = "[]"
    tags_final_json: str = "[]"
    confidence_value_id: str | None = None
    needs_review: bool | None = None
    is_transfer_candidate: bool | None = None
    is_transfer: bool | None = None
    transfer_group_id: str | None = None
    timezone_state: Literal["known", "unknown"] = "unknown"


@dataclass(frozen=True)
class OverviewFactRecord:
    """One typed Banksalad overview cell fact."""

    fact_id: str
    observation_id: str
    provenance_id: str
    snapshot_date: str
    sheet_name: str
    block_id: str
    block_title: str
    fact_kind: str
    value_type: Literal["number", "text", "date", "empty", "unsupported"]
    row_label: str | None = None
    column_label: str | None = None
    numeric_value_id: str | None = None
    value_text: str | None = None


@dataclass(frozen=True)
class OverviewBalanceRecord:
    """Typed balance projection kept distinct from transaction events."""

    balance_id: str
    observation_id: str
    provenance_id: str
    source_fact_id: str
    amount_value_id: str
    snapshot_date: str
    side: str
    category: str
    item_name: str


@dataclass(frozen=True)
class OverviewCashflowRecord:
    """Typed monthly cashflow projection."""

    cashflow_id: str
    observation_id: str
    provenance_id: str
    source_fact_id: str
    amount_value_id: str
    snapshot_date: str
    period_month: str
    category: str


@dataclass(frozen=True)
class OverviewInsuranceRecord:
    """Typed insurance projection."""

    insurance_id: str
    observation_id: str
    provenance_id: str
    source_fact_id: str
    paid_amount_value_id: str | None
    snapshot_date: str
    institution: str
    policy_name: str
    contract_status: str | None = None
    contract_date: str | None = None
    maturity_date: str | None = None


@dataclass(frozen=True)
class OverviewInvestmentRecord:
    """Typed investment projection with separate exact amounts and rate."""

    investment_id: str
    observation_id: str
    provenance_id: str
    source_fact_id: str
    principal_value_id: str | None
    valuation_value_id: str | None
    return_rate_value_id: str | None
    snapshot_date: str
    institution: str
    product_name: str
    product_type: str | None = None
    start_date: str | None = None
    maturity_date: str | None = None


@dataclass(frozen=True)
class OverviewLoanRecord:
    """Typed loan projection with exact principal, balance, and rate."""

    loan_id: str
    observation_id: str
    provenance_id: str
    source_fact_id: str
    principal_value_id: str | None
    balance_value_id: str | None
    interest_rate_value_id: str | None
    snapshot_date: str
    institution: str
    product_name: str
    loan_type: str | None = None
    start_date: str | None = None
    maturity_date: str | None = None


@dataclass(frozen=True)
class AssetSnapshotRecord:
    """Typed asset position, distinct from overview summary and transactions."""

    snapshot_id: str
    observation_id: str
    provenance_id: str
    account_id: str
    resource_id: str
    quantity_value_id: str | None
    market_value_id: str | None
    snapshot_date: str


@dataclass(frozen=True)
class OwnershipAssertionRecord:
    """Effective-dated, evidenced ownership state for one account."""

    assertion_id: str
    account_id: str
    completeness: Literal["complete", "partial", "unknown"]
    confirmation_state: Literal["unconfirmed", "confirmed", "rejected"]
    evidence: Mapping[str, Any]
    effective_from: str | None = None
    effective_to: str | None = None
    unknown_remainder: bool = True
    confirmed_at: str | None = None
    supersedes_assertion_id: str | None = None


@dataclass(frozen=True)
class OwnershipShareRecord:
    """One party's exact share in an ownership assertion set."""

    assertion_id: str
    party_id: str
    share_value_id: str


@dataclass(frozen=True)
class EntityRelationAssertionRecord:
    """Evidenced inclusion or overlap relation between two stable entities."""

    assertion_id: str
    subject_entity_id: str
    object_entity_id: str
    relation_kind: Literal["includes", "overlaps", "excludes", "unknown"]
    confirmation_state: Literal["unconfirmed", "confirmed", "rejected"]
    evidence: Mapping[str, Any]
    effective_from: str | None = None
    effective_to: str | None = None
    confirmed_at: str | None = None
    supersedes_assertion_id: str | None = None


@dataclass(frozen=True)
class AgentIntakeArtifactRecord:
    """Immutable evidence object registered for agent-assisted intake."""

    intake_artifact_id: str
    source_artifact_id: str
    media_type: str
    evidence: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class AgentIntakeOccurrenceRecord:
    """One receipt occurrence of an immutable intake artifact."""

    occurrence_id: str
    intake_artifact_id: str
    channel: str
    received_at: str
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class AgentIntakeExtractionRecord:
    """Machine extraction kept separate from evidence and interpretation."""

    extraction_id: str
    occurrence_id: str
    extractor: str
    payload: Mapping[str, Any] | list[Any]
    created_at: str


@dataclass(frozen=True)
class AgentIntakeProposalRecord:
    """Proposed mutation with its own optimistic-concurrency identity."""

    proposal_id: str
    extraction_id: str
    policy_version: str
    command_scope: str
    idempotency_key: str
    expected_generation: str
    expected_revision: int
    payload: Mapping[str, Any] | list[Any]
    created_at: str


@dataclass(frozen=True)
class AgentIntakeConfirmationRecord:
    """Explicit human confirmation or rejection of an intake proposal."""

    confirmation_id: str
    proposal_id: str
    confirmation_state: Literal["confirmed", "rejected"]
    actor: str
    detail: Mapping[str, Any]
    confirmed_at: str


@dataclass(frozen=True)
class AgentIntakeApplicationRecord:
    """Link a confirmed proposal to the single changeset that applied it."""

    proposal_id: str
    confirmation_id: str
    changeset_id: str
    applied_at: str
