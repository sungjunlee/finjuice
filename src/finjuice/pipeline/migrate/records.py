"""Map frozen records onto the isolated SQLite repository builder."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finjuice.pipeline.migrate.encoding import hex_digest
from finjuice.pipeline.migrate.inventory import resolve_entry_path
from finjuice.pipeline.migrate.preserve import money_currency
from finjuice.pipeline.migrate.types import (
    ORIGIN_KIND,
    PARSER_VERSION,
    CaptureEntry,
    CaptureManifest,
    Disposition,
)
from finjuice.pipeline.storage.csv_schema import ASSET_SNAPSHOT_COLUMNS, CSV_COLUMNS
from finjuice.pipeline.storage.csv_schema_cluster import (
    BANKSALAD_BALANCE_COLUMNS,
    BANKSALAD_CASHFLOW_COLUMNS,
    BANKSALAD_INSURANCE_COLUMNS,
    BANKSALAD_INVESTMENT_COLUMNS,
    BANKSALAD_LOAN_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
)
from finjuice.pipeline.storage.sqlite import (
    UNKNOWN_CURRENCY,
    AccountRecord,
    ConfigRevisionRecord,
    ExactValue,
    LegacyIdentifierRecord,
    MigrationIdentityRecord,
    ObservationRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    ResourceRecord,
    SourceOccurrenceRecord,
    migration_entity_id,
)
from finjuice.pipeline.storage.sqlite.errors import ExactValueError
from finjuice.pipeline.storage.sqlite.records import EntityKind

_TRANSACTION_KNOWN = set(CSV_COLUMNS)
_FACT_KNOWN = set(BANKSALAD_OVERVIEW_FACT_COLUMNS)
_BALANCE_KNOWN = set(BANKSALAD_BALANCE_COLUMNS)
_CASHFLOW_KNOWN = set(BANKSALAD_CASHFLOW_COLUMNS)
_INSURANCE_KNOWN = set(BANKSALAD_INSURANCE_COLUMNS)
_INVESTMENT_KNOWN = set(BANKSALAD_INVESTMENT_COLUMNS)
_LOAN_KNOWN = set(BANKSALAD_LOAN_COLUMNS)
_ASSET_KNOWN = set(ASSET_SNAPSHOT_COLUMNS)
_VALUE_TYPES = {"number", "text", "date", "empty", "unsupported"}


@dataclass
class BuildState:
    """Mutable ID maps for one preservation build."""

    builder: RepositoryBuilder
    digest: str
    fact_ids: dict[str, str] = field(default_factory=dict)
    projection_facts: dict[tuple[str, str], str] = field(default_factory=dict)
    accounts: dict[tuple[str, str], str] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)
    dispositions: list[tuple[str, Disposition, str]] = field(default_factory=list)
    issues: int = 0
    issue_ids: set[str] = field(default_factory=set)
    origin_artifact_id: str = ""
    origin_occurrence_id: str = ""


@dataclass(frozen=True)
class RowWork:
    """One CSV occurrence being mapped into the staging repository."""

    state: BuildState
    entry: CaptureEntry
    occurrence_id: str
    headers: list[str]
    ordinal: int
    row: dict[str, str]


def stable_id(digest: str, record_kind: str, locator: dict[str, Any]) -> str:
    """Return the contract UUIDv5 for one frozen locator."""
    return migration_entity_id(digest, record_kind, locator)


def add_identity(
    state: BuildState,
    entity_id: str,
    record_kind: EntityKind,
    locator: dict[str, Any],
) -> None:
    """Persist the frozen derivation inputs for one entity."""
    state.builder.add_migration_identity(
        MigrationIdentityRecord(
            entity_id=entity_id,
            capture_manifest_digest=state.digest,
            record_kind=record_kind,
            legacy_locator=locator,
        )
    )


def add_issue(
    state: BuildState,
    provenance_id: str,
    issue_kind: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record one typed preservation problem."""
    extra = extra or {}
    field_name = extra.get("field_name") if extra else None
    lexical_value = extra.get("lexical_value") if extra else None
    detail = extra.get("detail")
    locator = {
        "provenance_id": provenance_id,
        "issue_kind": issue_kind,
        "field_name": field_name or "",
    }
    issue_id = stable_id(state.digest, "preservation_issue", locator)
    if issue_id in state.issue_ids:
        return
    state.issue_ids.add(issue_id)
    state.builder.add_preservation_issue(
        PreservationIssueRecord(
            provenance_id=provenance_id,
            issue_kind=issue_kind,
            detail=detail or {"reason": issue_kind},
            field_name=field_name,
            lexical_value=lexical_value,
            issue_id=issue_id,
        )
    )
    state.issues += 1


def close_record(
    state: BuildState,
    provenance_id: str,
    payload: dict[str, Any],
    locator: dict[str, Any],
    result: tuple[Disposition, str],
) -> None:
    """Attach payload and disposition for one input."""
    disposition, reason = result
    state.builder.add_legacy_payload(
        provenance_id,
        payload,
        payload_id=stable_id(state.digest, "legacy_payload", locator),
    )
    state.builder.add_migration_disposition(provenance_id, disposition, reason)
    state.dispositions.append((provenance_id, disposition, reason))


def publish_entry(state: BuildState, manifest: CaptureManifest, entry: CaptureEntry) -> str:
    """Publish frozen bytes and register one source occurrence."""
    path = resolve_entry_path(manifest, entry)
    artifact = state.builder.publish_source_path(path)
    locator = {
        "locator_version": 1,
        "relative_path": entry.relative_path,
        "artifact_digest": hex_digest(artifact.artifact_id),
        "logical_role": entry.logical_role,
    }
    occurrence_id = stable_id(state.digest, "source_occurrence", locator)
    state.builder.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind=entry.logical_role,
            original_filename=Path(entry.relative_path or "").name or None,
            parser_version=PARSER_VERSION,
            source_schema_version=None,
            legacy_path=entry.relative_path,
        )
    )
    add_identity(state, occurrence_id, "source_occurrence", locator)
    return occurrence_id


def add_provenance(
    state: BuildState,
    occurrence_id: str,
    locator: dict[str, Any],
    coordinate: dict[str, Any],
) -> str:
    """Add one non-collapsing provenance row."""
    provenance_id = stable_id(state.digest, "provenance", locator)
    state.builder.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=occurrence_id,
            source_coordinate=coordinate,
            legacy_locator=locator,
            parser_version=PARSER_VERSION,
        )
    )
    return provenance_id


def ensure_account(state: BuildState, source: str, key: str, display: str) -> str:
    """Return a stable account ID without merging distinct source keys."""
    cache_key = (source, key)
    existing = state.accounts.get(cache_key)
    if existing is not None:
        return existing
    locator = {"locator_version": 1, "source": source, "account_key": key}
    account_id = stable_id(state.digest, "account", locator)
    state.builder.add_account(
        AccountRecord(
            account_id=account_id,
            account_kind="legacy.v1",
            display_name=display,
            ownership_state="unknown",
        )
    )
    add_identity(state, account_id, "account", locator)
    state.builder.add_legacy_identifier(
        LegacyIdentifierRecord(
            entity_id=account_id,
            identifier_kind="account_text",
            identifier_value=key,
            capture_manifest_digest=state.digest,
            mapping_id=stable_id(
                state.digest,
                "legacy_identifier",
                {**locator, "identifier_kind": "account_text"},
            ),
        )
    )
    state.accounts[cache_key] = account_id
    return account_id


def ensure_resource(state: BuildState, instrument_id: str) -> str:
    """Return a stable resource ID for one legacy instrument key."""
    existing = state.resources.get(instrument_id)
    if existing is not None:
        return existing
    locator = {"locator_version": 1, "instrument_id": instrument_id}
    resource_id = stable_id(state.digest, "resource", locator)
    state.builder.add_resource(
        ResourceRecord(
            resource_id=resource_id,
            resource_kind="instrument.v1",
            display_name=instrument_id,
        )
    )
    add_identity(state, resource_id, "resource", locator)
    state.resources[instrument_id] = resource_id
    return resource_id


def add_observation(state: BuildState, occurrence_id: str, locator: dict[str, Any]) -> str:
    """Add an unconfirmed observation that does not invent event time."""
    observation_id = stable_id(state.digest, "observation", locator)
    state.builder.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=occurrence_id,
            observed_at=None,
            effective_at=locator.get("date") or None,
            collected_at=None,
            scope_state="unknown",
            confirmation_state="unconfirmed",
        )
    )
    add_identity(state, observation_id, "observation", locator)
    return observation_id


def add_money(
    state: BuildState,
    provenance_id: str,
    locator: dict[str, Any],
    field: tuple[str, str, str | None],
) -> tuple[str | None, str | None]:
    """Parse one money field or report why it stayed untyped."""
    field_name, lexical, currency_raw = field
    currency, unknown, currency_issue = money_currency(currency_raw)
    if currency_issue:
        add_issue(
            state,
            provenance_id,
            currency_issue,
            {"field_name": "currency", "lexical_value": currency_raw},
        )
    try:
        value = ExactValue.from_lexical(
            lexical,
            value_kind="money",
            origin_kind="migration",
            currency=UNKNOWN_CURRENCY if unknown else currency,
        )
    except ExactValueError:
        add_issue(
            state,
            provenance_id,
            "unparseable_amount",
            {"field_name": field_name, "lexical_value": lexical},
        )
        return None, "unparseable_amount"
    value_id = stable_id(state.digest, "exact_value", {**locator, "field": field_name})
    state.builder.add_exact_value(value_id, value, provenance_id=provenance_id)
    return value_id, None


def add_typed_number(
    state: BuildState,
    provenance_id: str,
    locator: dict[str, Any],
    spec: dict[str, str],
) -> str | None:
    """Parse a non-money exact value or record an issue."""
    lexical = spec["lexical"]
    field_name = spec["field_name"]
    unit = spec["unit"]
    value_kind = spec.get("value_kind", "number")
    try:
        value = ExactValue.from_lexical(
            lexical,
            value_kind=value_kind,  # type: ignore[arg-type]
            origin_kind="migration",
            unit=unit,
        )
    except ExactValueError:
        add_issue(
            state,
            provenance_id,
            "unparseable_amount",
            {"field_name": field_name, "lexical_value": lexical},
        )
        return None
    value_id = stable_id(state.digest, "exact_value", {**locator, "field": field_name})
    state.builder.add_exact_value(value_id, value, provenance_id=provenance_id)
    return value_id


def row_locator(
    entry: CaptureEntry,
    ordinal: int,
    row: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a locator that distinguishes duplicate row_hash occurrences."""
    locator: dict[str, Any] = {
        "locator_version": 1,
        "relative_path": entry.relative_path,
        "partition_digest": hex_digest(entry.sha256 or ""),
        "ordinal": ordinal,
        "logical_role": entry.logical_role,
    }
    if row.get("row_hash"):
        locator["row_hash"] = row["row_hash"]
    if row.get("source_row") != "" and row.get("source_row") is not None:
        locator["source_row"] = row.get("source_row")
    if extra:
        locator.update(extra)
    return locator


def add_row_identifiers(
    work: RowWork,
    entity_id: str,
    provenance_id: str,
    locator: dict[str, Any],
) -> None:
    """Append permanent legacy identifier mappings for one occurrence."""
    identifiers = (
        ("row_hash", work.row.get("row_hash")),
        ("file_id", work.row.get("file_id")),
        ("source_row", work.row.get("source_row")),
        ("fact_id", work.row.get("fact_id") or work.row.get("source_fact_id")),
        ("old_path", work.entry.relative_path),
    )
    for kind, value in identifiers:
        if not value:
            continue
        work.state.builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=entity_id,
                identifier_kind=kind,  # type: ignore[arg-type]
                identifier_value=value,
                capture_manifest_digest=work.state.digest,
                provenance_id=provenance_id,
                mapping_id=stable_id(
                    work.state.digest,
                    "legacy_identifier",
                    {**locator, "identifier_kind": kind, "identifier_value": value},
                ),
            )
        )


def add_origin_revision(state: BuildState, capture_bytes: bytes) -> None:
    """Record current frozen state as one synthetic legacy_current_state revision."""
    artifact = state.builder.publish_source(io.BytesIO(capture_bytes))
    locator = {"locator_version": 1, "origin_kind": ORIGIN_KIND}
    occurrence_id = stable_id(state.digest, "source_occurrence", locator)
    state.builder.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind=ORIGIN_KIND,
            parser_version=PARSER_VERSION,
            legacy_path=None,
        )
    )
    add_identity(state, occurrence_id, "source_occurrence", locator)
    revision_id = stable_id(state.digest, "config_revision", locator)
    state.builder.add_config_revision(
        ConfigRevisionRecord(
            revision_id=revision_id,
            config_kind="other",
            artifact_id=artifact.artifact_id,
            occurrence_id=occurrence_id,
            parsed_status="parsed",
            parser_version=PARSER_VERSION,
            canonical_payload={
                "origin_kind": ORIGIN_KIND,
                "capture_manifest_digest": state.digest,
                "note": "Current frozen state only; not a historical event sequence.",
            },
        )
    )
    add_identity(state, revision_id, "config_revision", locator)
    state.origin_artifact_id = artifact.artifact_id
    state.origin_occurrence_id = occurrence_id
