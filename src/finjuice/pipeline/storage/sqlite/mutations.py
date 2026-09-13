"""Single atomic mutation boundary for the active authoritative repository."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, TypeAlias

from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    RepositoryAuthority,
    read_activation,
    require_repository_binding,
    shared_write_lease,
)
from finjuice.pipeline.storage.sqlite.errors import (
    MutationAbortedError,
    MutationBusyError,
    MutationConflictError,
    MutationValidationError,
    RepositoryIntegrityError,
)
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.exact_import.lookup import (
    load_completed_exact_imports,
    load_transaction_identity_snapshot,
)
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import (
    SourceArtifact,
    SourceObjectStore,
    _assert_no_symlink_ancestors,
)
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    AgentIntakeApplicationRecord,
    AgentIntakeArtifactRecord,
    AgentIntakeConfirmationRecord,
    AgentIntakeExtractionRecord,
    AgentIntakeOccurrenceRecord,
    AgentIntakeProposalRecord,
    AssetSnapshotRecord,
    ConfigRevisionRecord,
    EntityRelationAssertionRecord,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
    OwnershipAssertionRecord,
    OwnershipShareRecord,
    PartyRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    ResourceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
    TransactionSourceLinkRecord,
)
from finjuice.pipeline.storage.sqlite.schema import (
    _OWNERSHIP_SHARE_UNIT,
    SQLITE_APPLICATION_ID,
    SQLITE_SCHEMA_VERSION,
    _is_canonical_calendar_date,
    _validate_intake_applications,
    _validate_ownership_assertions,
    _validate_relation_assertions,
    _validate_v3_invariants,
    _validate_v4_invariants,
)
from finjuice.pipeline.storage.sqlite.writes import TypedRowWriter

JSONValue: TypeAlias = Any
MutationHandler: TypeAlias = Callable[["MutationContext"], "MutationOutcome"]
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_MAX_KEY_LENGTH = 512
_DEFAULT_BUSY_TIMEOUT_MS = 5_000
_PREVIEW_CHANGESET_ID = "preview"
_DERIVED_COLUMNS: Final[dict[str, str]] = {
    "category_final": "category_final",
    "category_rule": "category_rule",
    "confidence_value_id": "confidence_value_id",
    "is_transfer": "is_transfer",
    "is_transfer_candidate": "is_transfer_candidate",
    "needs_review": "needs_review",
    "tags_final": "tags_final_json",
    "tags_rule": "tags_rule_json",
    "transfer_group_id": "transfer_group_id",
}
_JSON_DERIVED_KEYS = frozenset({"tags_final", "tags_rule"})
_BOOL_DERIVED_KEYS = frozenset({"is_transfer", "is_transfer_candidate", "needs_review"})


@dataclass(frozen=True)
class MutationRequest:
    """Stable request identity and optimistic-concurrency preconditions."""

    command_scope: str
    idempotency_key: str
    payload: Mapping[str, JSONValue]
    expected_generation: str
    expected_revision: int
    actor: str
    reason: str | None = None
    confirmation: Mapping[str, JSONValue] | None = None
    reversal_of_changeset_id: str | None = None


@dataclass(frozen=True)
class MutationOutcome:
    """Stored command response and immutable artifacts retained around the transaction."""

    result: Mapping[str, JSONValue]
    retained_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class MutationReceipt:
    """Durable result envelope returned by an original mutation or identical retry."""

    changeset_id: str
    base_revision: int
    committed_revision: int
    state_changed: bool
    result: Mapping[str, JSONValue]
    retained_artifacts: tuple[str, ...]
    replayed: bool = False


@dataclass(frozen=True)
class ConfigRevisionMutation:
    """One exact configuration document selected as the new canonical head."""

    revision: ConfigRevisionRecord
    occurrence: SourceOccurrenceRecord
    artifact: SourceArtifact
    updated_at: str


@dataclass(frozen=True)
class ManualTransactionEdit:
    """Manual classification and note changes for one stable transaction."""

    identifier: str
    add_tags: tuple[str, ...] = ()
    remove_tags: tuple[str, ...] = ()
    category_supplied: bool = False
    category: str | None = None
    note_supplied: bool = False
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise MutationValidationError("Transaction identifier must be explicit.")
        for tag in (*self.add_tags, *self.remove_tags):
            if not isinstance(tag, str) or not tag.strip():
                raise MutationValidationError("Manual tags must be non-empty strings.")
        if self.category is not None and not self.category.strip():
            raise MutationValidationError("Manual category must be non-empty when supplied.")
        if self.note is not None and len(self.note) > 1_000:
            raise MutationValidationError("Manual note cannot exceed 1000 characters.")


@dataclass(frozen=True)
class _ChangeEntry:
    entity_kind: str
    entity_id: str
    action: str
    before: Mapping[str, JSONValue] | None
    after: Mapping[str, JSONValue] | None


@dataclass(frozen=True)
class _CommitState:
    changeset_id: str
    base_revision: int
    committed_revision: int
    state_changed: bool
    created_at: str
    payload_digest: str


@dataclass
class _AttemptState:
    context: MutationContext | None = None
    outcome: MutationOutcome | None = None


@dataclass(frozen=True)
class _TransactionInputs:
    authority: RepositoryAuthority
    request: MutationRequest
    request_digest: str
    current_revision: int
    handler: MutationHandler


class MutationContext:
    """Typed domain writes that automatically capture complete audit deltas."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: RepositoryAuthority,
        changeset_id: str,
    ) -> None:
        self.__connection = connection
        self.__writer = TypedRowWriter(connection)
        self.authority = authority
        self.changeset_id = changeset_id
        self.__entries: list[_ChangeEntry] = []
        self.__retained_artifacts: list[str] = []
        self.__savepoint_serial = 0

    @property
    def entries(self) -> tuple[_ChangeEntry, ...]:
        return tuple(self.__entries)

    @property
    def retained_artifacts(self) -> tuple[str, ...]:
        return tuple(self.__retained_artifacts)

    def retain_artifact(self, artifact_id: str) -> None:
        """Report an immutable object that remains after transaction rollback."""
        if not isinstance(artifact_id, str) or not artifact_id:
            raise MutationValidationError("Retained artifact identity must be explicit.")
        if artifact_id not in self.__retained_artifacts:
            self.__retained_artifacts.append(artifact_id)

    def register_source_artifact(self, artifact: SourceArtifact) -> None:
        """Register a pre-published immutable object after verifying it in this generation."""
        verified = SourceObjectStore(self.authority.paths).verify(
            artifact.artifact_id,
            expected_size=artifact.byte_length,
        )
        if (
            verified.artifact_id != artifact.artifact_id
            or verified.digest_hex != artifact.digest_hex
            or verified.byte_length != artifact.byte_length
            or verified.relative_path != artifact.relative_path
        ):
            raise MutationValidationError("Source artifact metadata is not canonical.")
        self.retain_artifact(artifact.artifact_id)
        self.__connection.execute(
            "INSERT OR IGNORE INTO source_artifacts "
            "(source_artifact_id, digest_hex, byte_length, object_path) VALUES (?, ?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.digest_hex,
                artifact.byte_length,
                artifact.relative_path,
            ),
        )
        if self.__connection.execute("SELECT changes()").fetchone()[0]:
            self._record("source_artifact", artifact.artifact_id, "insert", None, asdict(artifact))

    def replace_config(self, mutation: ConfigRevisionMutation) -> bool:
        """Append exact config bytes and atomically select them as the canonical head."""
        revision = mutation.revision
        occurrence = mutation.occurrence
        if occurrence.artifact_id != mutation.artifact.artifact_id:
            raise MutationValidationError("Config occurrence must reference its exact artifact.")
        if revision.artifact_id != mutation.artifact.artifact_id:
            raise MutationValidationError("Config revision must reference its exact artifact.")
        if revision.occurrence_id != occurrence.occurrence_id:
            raise MutationValidationError("Config revision must reference its occurrence.")
        current = self.__connection.execute(
            "SELECT revision.entity_id, revision.source_artifact_id, revision.parsed_status, "
            "revision.parser_version, revision.canonical_payload_json "
            "FROM config_heads AS head "
            "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
            "WHERE head.config_kind = ?",
            (revision.config_kind,),
        ).fetchone()
        canonical_payload_json = (
            None
            if revision.canonical_payload is None
            else _canonical_request_json(revision.canonical_payload)
        )
        if current is not None and (
            str(current[1]) == revision.artifact_id
            and str(current[2]) == revision.parsed_status
            and (None if current[3] is None else str(current[3])) == revision.parser_version
            and (None if current[4] is None else str(current[4])) == canonical_payload_json
        ):
            return False

        self.register_source_artifact(mutation.artifact)
        self._insert_config_occurrence(occurrence)
        self._insert_config_revision(revision)
        after = _config_audit_state(revision)
        self._record("config_revision", revision.revision_id, "insert", None, after)
        if current is None:
            self.__connection.execute(
                "INSERT INTO config_heads "
                "(config_kind, revision_id, updated_changeset_id, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    revision.config_kind,
                    revision.revision_id,
                    self.changeset_id,
                    mutation.updated_at,
                ),
            )
            before = None
            action = "insert"
        else:
            before = {
                "artifact_id": str(current[1]),
                "parsed_status": str(current[2]),
                "parser_version": None if current[3] is None else str(current[3]),
                "revision_id": str(current[0]),
            }
            updated = self.__connection.execute(
                "UPDATE config_heads SET revision_id = ?, updated_changeset_id = ?, "
                "updated_at = ? WHERE config_kind = ? AND revision_id = ?",
                (
                    revision.revision_id,
                    self.changeset_id,
                    mutation.updated_at,
                    revision.config_kind,
                    current[0],
                ),
            )
            if updated.rowcount != 1:
                raise MutationConflictError("Canonical config head changed during mutation.")
            action = "update"
        self._record("config_head", revision.config_kind, action, before, after)
        return True

    def config_head_revision_id(self, config_kind: str) -> str | None:
        """Return the selected config revision inside this mutation transaction."""
        row = self.__connection.execute(
            "SELECT revision_id FROM config_heads WHERE config_kind = ?",
            (config_kind,),
        ).fetchone()
        return None if row is None else str(row[0])

    def read_config_bytes(self, config_kind: str) -> bytes | None:
        """Read the selected exact config while holding the mutation transaction."""
        row = self.__connection.execute(
            "SELECT artifact.source_artifact_id, artifact.byte_length "
            "FROM config_heads AS head "
            "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
            "JOIN source_artifacts AS artifact "
            "ON artifact.source_artifact_id = revision.source_artifact_id "
            "WHERE head.config_kind = ?",
            (config_kind,),
        ).fetchone()
        if row is None:
            return None
        artifact = SourceObjectStore(self.authority.paths).verify(str(row[0]), int(row[1]))
        return (self.authority.paths.root / artifact.relative_path).read_bytes()

    def _insert_config_occurrence(self, occurrence: SourceOccurrenceRecord) -> None:
        self.__writer.add_source_occurrence(occurrence)
        self._record(
            "source_occurrence",
            occurrence.occurrence_id,
            "insert",
            None,
            asdict(occurrence),
        )

    def _insert_config_revision(self, revision: ConfigRevisionRecord) -> None:
        validate_entity_id(revision.revision_id)
        payload_json = (
            None
            if revision.canonical_payload is None
            else _canonical_request_json(revision.canonical_payload)
        )
        self.__connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'config_revision')",
            (revision.revision_id,),
        )
        self.__connection.execute(
            "INSERT INTO config_revisions "
            "(entity_id, config_kind, source_artifact_id, source_occurrence_id, parsed_status, "
            "parser_version, canonical_payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                revision.revision_id,
                revision.config_kind,
                revision.artifact_id,
                revision.occurrence_id,
                revision.parsed_status,
                revision.parser_version,
                payload_json,
            ),
        )

    def edit_manual_transaction(
        self,
        edit: ManualTransactionEdit,
    ) -> Mapping[str, JSONValue]:
        """Patch manual classification fields on one unambiguous stable entity."""
        from finjuice.pipeline.tagging.manual import merge_final_tags

        transaction_id = self._resolve_transaction_id(edit.identifier.strip())
        current = self._load_manual_transaction(transaction_id)
        remove_tags = set(edit.remove_tags)
        next_manual = [tag for tag in current["tags_manual"] if tag not in remove_tags]
        if edit.add_tags or edit.remove_tags or edit.category_supplied:
            next_manual = merge_final_tags(next_manual, edit.add_tags)
        next_category = edit.category if edit.category_supplied else current["category_manual"]
        next_note = edit.note if edit.note_supplied else current["notes_manual"]
        classification_requested = bool(edit.add_tags or edit.remove_tags or edit.category_supplied)
        if classification_requested:
            next_final_tags = merge_final_tags(
                current["tags_rule"], current["tags_ai"], next_manual
            )
            next_category_final = _resolve_manual_category(
                next_category,
                current["category_rule"],
                current["minor_raw"],
                current["major_raw"],
            )
        else:
            next_final_tags = current["tags_final"]
            next_category_final = current["category_final"]
        confidence_value_id = current["confidence_value_id"]
        confidence_exact = current["confidence_exact"]
        needs_review = current["needs_review"]
        if classification_requested:
            confidence_target = int(bool(next_final_tags) or next_category is not None)
            if not _exact_equals_integer(
                current["confidence_coefficient"],
                current["confidence_scale"],
                confidence_target,
            ):
                confidence_value_id = new_entity_id()
                self.add_exact_value(
                    confidence_value_id,
                    ExactValue(
                        coefficient=str(confidence_target),
                        scale=0,
                        lexical=None,
                        value_kind="number",
                        origin_kind="calculated",
                        unit="confidence.v1",
                    ),
                )
                confidence_exact = str(confidence_target)
            needs_review = confidence_target == 0
        before = _manual_audit_state(current)
        result_state = {
            "category_final": next_category_final,
            "category_manual": next_category,
            "confidence_exact": confidence_exact,
            "needs_review": needs_review,
            "notes_manual": next_note,
            "tags_final": next_final_tags,
            "tags_manual": next_manual,
        }
        after = dict(result_state)
        if not classification_requested:
            after.update(
                {
                    "category_final": before["category_final"],
                    "category_manual": before["category_manual"],
                    "confidence_exact": before["confidence_exact"],
                    "needs_review": before["needs_review"],
                    "tags_final": before["tags_final"],
                    "tags_manual": before["tags_manual"],
                }
            )
        if before != after:
            assignments: list[str] = []
            parameters: list[Any] = []
            if edit.note_supplied and before["notes_manual"] != after["notes_manual"]:
                assignments.append("notes_manual = ?")
                parameters.append(next_note)
            if classification_requested:
                assignments.extend(
                    (
                        "category_manual = ?",
                        "category_final = ?",
                        "tags_manual_json = ?",
                        "tags_final_json = ?",
                        "confidence_value_id = ?",
                        "needs_review = ?",
                    )
                )
                parameters.extend(
                    (
                        next_category,
                        next_category_final,
                        _canonical_request_json(next_manual),
                        _canonical_request_json(next_final_tags),
                        confidence_value_id,
                        None if needs_review is None else int(needs_review),
                    )
                )
            if not assignments:
                raise RepositoryIntegrityError("Manual edit changed state without a typed field.")
            parameters.append(transaction_id)
            self.__connection.execute(
                f"UPDATE transactions SET {', '.join(assignments)} "  # nosec B608
                "WHERE entity_id = ?",
                parameters,
            )
            self._record("transaction", transaction_id, "update", before, after)
        return {
            "transaction_id": transaction_id,
            **_manual_transaction_view(current),
            **after,
        }

    def _resolve_transaction_id(self, identifier: str) -> str:
        try:
            validate_entity_id(identifier)
        except ValueError:
            pass
        else:
            exists = self.__connection.execute(
                "SELECT 1 FROM transactions WHERE entity_id = ?",
                (identifier,),
            ).fetchone()
            if exists is not None:
                return identifier
        rows = self.__connection.execute(
            "SELECT DISTINCT mapping.entity_id FROM legacy_identifiers AS mapping "
            "LEFT JOIN legacy_identifier_supersessions AS supersession "
            "ON supersession.previous_mapping_id = mapping.mapping_id "
            "JOIN transactions AS txn ON txn.entity_id = mapping.entity_id "
            "WHERE mapping.identifier_kind = 'row_hash' AND mapping.identifier_value = ? "
            "AND supersession.previous_mapping_id IS NULL ORDER BY mapping.entity_id",
            (identifier,),
        ).fetchall()
        if not rows:
            raise MutationValidationError("Transaction identifier was not found.")
        if len(rows) != 1:
            raise MutationValidationError(
                "Legacy row_hash identifies multiple transactions; use a stable transaction ID."
            )
        return str(rows[0][0])

    def _load_manual_transaction(self, transaction_id: str) -> dict[str, Any]:
        row = self.__connection.execute(
            "SELECT txn.date_raw, txn.time_raw, txn.datetime_raw, txn.type_raw, "
            "txn.type_norm, txn.major_raw, txn.minor_raw, txn.merchant_raw, txn.memo_raw, "
            "txn.notes_manual, txn.account_text, txn.counterparty, txn.category_rule, "
            "txn.category_manual, txn.category_final, txn.tags_rule_json, txn.tags_ai_json, "
            "txn.tags_manual_json, txn.tags_final_json, txn.confidence_value_id, "
            "txn.needs_review, confidence.coefficient, confidence.scale, amount.coefficient, "
            "amount.scale, money.currency_code, txn.is_transfer_candidate, txn.is_transfer, "
            "txn.transfer_group_id FROM transactions AS txn "
            "LEFT JOIN exact_values AS confidence "
            "ON confidence.value_id = txn.confidence_value_id "
            "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id "
            "JOIN money_values AS money ON money.value_id = txn.amount_value_id "
            "WHERE txn.entity_id = ?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            raise MutationValidationError("Transaction identifier was not found.")
        parse_tags = (
            _parse_preserved_string_array
            if _has_migrated_transaction_source(self.__connection, transaction_id)
            else _parse_string_array
        )
        coefficient = None if row[21] is None else str(row[21])
        scale = None if row[22] is None else int(row[22])
        return {
            "date_raw": row[0],
            "time_raw": row[1],
            "datetime_raw": row[2],
            "type_raw": row[3],
            "type_norm": row[4],
            "major_raw": row[5],
            "minor_raw": row[6],
            "merchant_raw": row[7],
            "memo_raw": row[8],
            "notes_manual": row[9],
            "account_text": row[10],
            "counterparty": row[11],
            "category_rule": row[12],
            "category_manual": row[13],
            "category_final": row[14],
            "tags_rule": parse_tags(row[15]),
            "tags_ai": parse_tags(row[16]),
            "tags_manual": parse_tags(row[17]),
            "tags_final": parse_tags(row[18]),
            "tags_manual_audit": None if row[17] is None else parse_tags(row[17]),
            "tags_final_audit": None if row[18] is None else parse_tags(row[18]),
            "confidence_value_id": row[19],
            "needs_review": None if row[20] is None else bool(row[20]),
            "confidence_coefficient": coefficient,
            "confidence_scale": scale,
            "confidence_exact": _exact_decimal_text(coefficient, scale),
            "amount_exact": _exact_decimal_text(str(row[23]), int(row[24])),
            "currency": row[25],
            "is_transfer_candidate": None if row[26] is None else bool(row[26]),
            "is_transfer": None if row[27] is None else bool(row[27]),
            "transfer_group_id": row[28],
        }

    def load_rules_head(self) -> tuple[str | None, bytes | None]:
        """Return parsed_status and exact bytes for the pinned rules head."""
        status = self._config_parsed_status("rules")
        if status is None:
            return None, None
        return status, self.read_config_bytes("rules")

    def load_bulk_transactions(
        self,
        transaction_ids: Sequence[str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Load tagging/transfer inputs in one snapshot batch."""
        return _load_bulk_transaction_rows(self.__connection, transaction_ids)

    def find_calculated_confidence(self, target: int) -> str | None:
        """Return an existing calculated coverage 0/1 value, if one is stored."""
        _require_coverage_target(target)
        row = self.__connection.execute(
            "SELECT exact.value_id FROM exact_values AS exact "
            "JOIN number_values AS number ON number.value_id = exact.value_id "
            "WHERE exact.value_kind = 'number' AND exact.origin_kind = 'calculated' "
            "AND number.unit = 'confidence.v1' AND exact.coefficient = ? "
            "AND exact.scale = 0 ORDER BY exact.value_id LIMIT 1",
            (str(target),),
        ).fetchone()
        return None if row is None else str(row[0])

    def allocate_calculated_confidence(self, target: int) -> str:
        """Insert one calculated coverage ExactValue and return its id."""
        _require_coverage_target(target)
        value_id = new_entity_id()
        self.add_exact_value(
            value_id,
            ExactValue(
                coefficient=str(target),
                scale=0,
                lexical=None,
                value_kind="number",
                origin_kind="calculated",
                unit="confidence.v1",
            ),
        )
        return value_id

    def update_transaction_derived_state(
        self,
        transaction_id: str,
        after: Mapping[str, JSONValue],
        *,
        before: Mapping[str, JSONValue],
    ) -> bool:
        """Patch allowed derived fields with parameterized SQL and before/after audit."""
        validate_entity_id(transaction_id)
        stored = _load_stored_derived_state(self.__connection, transaction_id)
        _reject_stale_derived_before(before, stored, after)
        assignments, parameters, audit_before, audit_after = _derived_update_parts(after, stored)
        if not assignments:
            return False
        self._execute_derived_update(transaction_id, assignments, parameters)
        self._record("transaction", transaction_id, "update", audit_before, audit_after)
        return True

    def _execute_derived_update(
        self,
        transaction_id: str,
        assignments: list[str],
        parameters: list[Any],
    ) -> None:
        parameters.append(transaction_id)
        updated = self.__connection.execute(
            f"UPDATE transactions SET {', '.join(assignments)} WHERE entity_id = ?",  # nosec B608
            parameters,
        )
        if updated.rowcount != 1:
            raise MutationValidationError("Transaction identifier was not found.")

    def _config_parsed_status(self, config_kind: str) -> str | None:
        row = self.__connection.execute(
            "SELECT revision.parsed_status FROM config_heads AS head "
            "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
            "WHERE head.config_kind = ?",
            (config_kind,),
        ).fetchone()
        return None if row is None else str(row[0])

    def add_exact_value(
        self,
        value_id: str,
        value: ExactValue,
        *,
        provenance_id: str | None = None,
    ) -> None:
        """Insert one exact value and semantic subtype without float conversion."""
        after = {"value_id": value_id, **asdict(value), "provenance_id": provenance_id}
        self._audited_insert(
            "exact_value",
            value_id,
            after,
            lambda: self.__writer.add_exact_value(value_id, value, provenance_id=provenance_id),
        )

    def add_source_occurrence(self, record: SourceOccurrenceRecord) -> None:
        """Add a distinct source occurrence and audit it after the typed insert succeeds."""
        self._audited_insert(
            "source_occurrence",
            record.occurrence_id,
            asdict(record),
            lambda: self.__writer.add_source_occurrence(record),
        )

    def add_provenance(self, record: ProvenanceRecord) -> None:
        """Add canonical source coordinates without collapsing equal legacy row hashes."""
        self._audited_insert(
            "record_provenance",
            record.provenance_id,
            asdict(record),
            lambda: self.__writer.add_provenance(record),
        )

    def add_party(self, record: PartyRecord) -> None:
        """Add a party foundation row."""
        self._audited_insert(
            "party", record.party_id, asdict(record), lambda: self.__writer.add_party(record)
        )

    def add_account(self, record: AccountRecord) -> None:
        """Add an account with explicit ownership state; no lookup or merge is attempted."""
        self._audited_insert(
            "account",
            record.account_id,
            asdict(record),
            lambda: self.__writer.add_account(record),
        )

    def add_resource(self, record: ResourceRecord) -> None:
        """Add a resource or instrument foundation row."""
        self._audited_insert(
            "resource",
            record.resource_id,
            asdict(record),
            lambda: self.__writer.add_resource(record),
        )

    def add_observation(self, record: ObservationRecord) -> None:
        """Add source-backed temporal and scope context."""
        self._audited_insert(
            "observation",
            record.observation_id,
            asdict(record),
            lambda: self.__writer.add_observation(record),
        )

    def add_transaction(self, record: TransactionRecord) -> None:
        """Add a typed transaction row; equal row hashes stay distinct by provenance."""
        self._audited_insert(
            "transaction",
            record.transaction_id,
            asdict(record),
            lambda: self.__writer.add_transaction(record),
        )

    def add_transaction_source_link(self, record: TransactionSourceLinkRecord) -> None:
        """Link source evidence to one accepted transaction without asserting ownership."""
        after = {**asdict(record), "created_changeset_id": self.changeset_id}
        _canonical_request_json(after)
        with self._source_link_savepoint():
            self._insert_transaction_source_link(record)
        self._record("transaction_source_link", record.link_id, "link", None, after)

    def add_overview_fact(self, record: OverviewFactRecord) -> None:
        """Add one typed overview fact."""
        self._audited_insert(
            "overview_fact",
            record.fact_id,
            asdict(record),
            lambda: self.__writer.add_overview_fact(record),
        )

    def add_overview_balance(self, record: OverviewBalanceRecord) -> None:
        """Add a typed overview balance."""
        self._audited_insert(
            "overview_balance",
            record.balance_id,
            asdict(record),
            lambda: self.__writer.add_overview_balance(record),
        )

    def add_overview_cashflow(self, record: OverviewCashflowRecord) -> None:
        """Add a typed overview cashflow."""
        self._audited_insert(
            "overview_cashflow",
            record.cashflow_id,
            asdict(record),
            lambda: self.__writer.add_overview_cashflow(record),
        )

    def add_overview_insurance(self, record: OverviewInsuranceRecord) -> None:
        """Add a typed overview insurance row."""
        self._audited_insert(
            "overview_insurance",
            record.insurance_id,
            asdict(record),
            lambda: self.__writer.add_overview_insurance(record),
        )

    def add_overview_investment(self, record: OverviewInvestmentRecord) -> None:
        """Add a typed overview investment row."""
        self._audited_insert(
            "overview_investment",
            record.investment_id,
            asdict(record),
            lambda: self.__writer.add_overview_investment(record),
        )

    def add_overview_loan(self, record: OverviewLoanRecord) -> None:
        """Add a typed overview loan row."""
        self._audited_insert(
            "overview_loan",
            record.loan_id,
            asdict(record),
            lambda: self.__writer.add_overview_loan(record),
        )

    def add_asset_snapshot(self, record: AssetSnapshotRecord) -> None:
        """Add a typed asset position snapshot."""
        self._audited_insert(
            "asset_snapshot",
            record.snapshot_id,
            asdict(record),
            lambda: self.__writer.add_asset_snapshot(record),
        )

    def add_legacy_payload(
        self,
        provenance_id: str,
        payload: Mapping[str, JSONValue] | Sequence[JSONValue],
        *,
        payload_id: str | None = None,
    ) -> str:
        """Preserve one full legacy payload next to its typed rows and return its ID."""
        payload_id = payload_id or new_entity_id()
        snapshot = list(payload) if not isinstance(payload, Mapping) else dict(payload)
        after = {"payload_id": payload_id, "provenance_id": provenance_id, "payload": snapshot}
        self._audited_insert(
            "legacy_payload",
            payload_id,
            after,
            lambda: self.__writer.add_legacy_payload(provenance_id, payload, payload_id=payload_id),
        )
        return payload_id

    def add_preservation_issue(self, record: PreservationIssueRecord) -> str:
        """Record a lossless typing or preservation problem and return its issue ID."""
        issue_id = record.issue_id or new_entity_id()
        stored = PreservationIssueRecord(**{**asdict(record), "issue_id": issue_id})
        self._audited_insert(
            "preservation_issue",
            issue_id,
            asdict(stored),
            lambda: self.__writer.add_preservation_issue(stored),
        )
        return issue_id

    def find_completed_exact_imports(
        self,
        digest_hex: str,
    ) -> tuple[Mapping[str, JSONValue], ...]:
        """Return completed exact-import manifests bound to one artifact digest."""
        return load_completed_exact_imports(self.__connection, digest_hex)

    def load_transaction_identity_snapshot(self) -> tuple[Mapping[str, JSONValue], ...]:
        """Load unproven-overlap identity fields for pinned transactions."""
        return load_transaction_identity_snapshot(self.__connection)

    def _insert_transaction_source_link(self, record: TransactionSourceLinkRecord) -> None:
        _validate_source_link_record(record)
        _validate_source_link_binding(self.__connection, record)
        self.__connection.execute(
            "INSERT INTO transaction_source_links "
            "(link_id, transaction_id, provenance_id, observation_id, link_kind, "
            "created_changeset_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.link_id,
                record.transaction_id,
                record.provenance_id,
                record.observation_id,
                record.link_kind,
                self.changeset_id,
            ),
        )

    @contextmanager
    def _source_link_savepoint(self) -> Iterator[None]:
        self.__savepoint_serial += 1
        name = f"source_link_{self.__savepoint_serial}"
        self.__connection.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self.__connection.execute(f"ROLLBACK TO {name}")
            self.__connection.execute(f"RELEASE {name}")
            raise
        else:
            self.__connection.execute(f"RELEASE {name}")

    def _audited_insert(
        self,
        entity_kind: str,
        entity_id: str,
        after: Mapping[str, JSONValue],
        write: Callable[[], Any],
    ) -> None:
        """Validate the audit snapshot, run one atomic typed write, then record the insert.

        The snapshot is checked before any row is touched so a rejected audit value (for
        example a float) never leaves typed rows without a matching changeset entry, even when
        the handler catches the error and continues.
        """
        _canonical_request_json(after)
        write()
        self._record(entity_kind, entity_id, "insert", None, after)

    def add_ownership_assertion(
        self,
        record: OwnershipAssertionRecord,
        shares: Sequence[OwnershipShareRecord],
    ) -> None:
        """Insert an immutable ownership assertion and its exact party shares."""
        validate_entity_id(record.assertion_id)
        validate_entity_id(record.account_id)
        if record.supersedes_assertion_id is not None:
            validate_entity_id(record.supersedes_assertion_id)
        _validate_mutation_effective_interval(record.effective_from, record.effective_to)
        evidence_json = _canonical_request_json(record.evidence)
        self.__connection.execute(
            "INSERT INTO ownership_assertion_sets "
            "(assertion_id, account_id, effective_from, effective_to, completeness, "
            "unknown_remainder, confirmation_state, evidence_json, confirmed_at, "
            "supersedes_assertion_id, created_changeset_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.assertion_id,
                record.account_id,
                record.effective_from,
                record.effective_to,
                record.completeness,
                int(record.unknown_remainder),
                record.confirmation_state,
                evidence_json,
                record.confirmed_at,
                record.supersedes_assertion_id,
                self.changeset_id,
            ),
        )
        for share in shares:
            if share.assertion_id != record.assertion_id:
                raise MutationValidationError("Ownership share references another assertion.")
            validate_entity_id(share.party_id)
            validate_entity_id(share.share_value_id)
            unit = self.__connection.execute(
                "SELECT unit FROM rate_values WHERE value_id = ?",
                (share.share_value_id,),
            ).fetchone()
            if unit is None or unit[0] != _OWNERSHIP_SHARE_UNIT:
                raise MutationValidationError(
                    "Ownership shares must use the ownership_share.v1 semantic unit."
                )
            self.__connection.execute(
                "INSERT INTO ownership_assertion_shares "
                "(assertion_id, party_id, share_value_id) VALUES (?, ?, ?)",
                (share.assertion_id, share.party_id, share.share_value_id),
            )
        after = {**asdict(record), "shares": [asdict(share) for share in shares]}
        self._record("ownership_assertion", record.assertion_id, "assert", None, after)

    def add_relation_assertion(self, record: EntityRelationAssertionRecord) -> None:
        """Insert one immutable evidenced relation assertion."""
        for identifier in (
            record.assertion_id,
            record.subject_entity_id,
            record.object_entity_id,
        ):
            validate_entity_id(identifier)
        if record.supersedes_assertion_id is not None:
            validate_entity_id(record.supersedes_assertion_id)
        _validate_mutation_effective_interval(record.effective_from, record.effective_to)
        self.__connection.execute(
            "INSERT INTO entity_relation_assertions "
            "(assertion_id, subject_entity_id, object_entity_id, relation_kind, effective_from, "
            "effective_to, confirmation_state, evidence_json, confirmed_at, "
            "supersedes_assertion_id, created_changeset_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.assertion_id,
                record.subject_entity_id,
                record.object_entity_id,
                record.relation_kind,
                record.effective_from,
                record.effective_to,
                record.confirmation_state,
                _canonical_request_json(record.evidence),
                record.confirmed_at,
                record.supersedes_assertion_id,
                self.changeset_id,
            ),
        )
        self._record(
            "entity_relation_assertion", record.assertion_id, "assert", None, asdict(record)
        )

    def add_intake_artifact(self, record: AgentIntakeArtifactRecord) -> None:
        """Register immutable intake evidence separately from later interpretation."""
        validate_entity_id(record.intake_artifact_id)
        self.__connection.execute(
            "INSERT INTO agent_intake_artifacts "
            "(intake_artifact_id, source_artifact_id, media_type, evidence_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.intake_artifact_id,
                record.source_artifact_id,
                record.media_type,
                _canonical_request_json(record.evidence),
                record.created_at,
            ),
        )
        self._record(
            "agent_intake_artifact", record.intake_artifact_id, "insert", None, asdict(record)
        )

    def add_intake_occurrence(self, record: AgentIntakeOccurrenceRecord) -> None:
        """Add one occurrence of already registered intake evidence."""
        validate_entity_id(record.occurrence_id)
        self.__connection.execute(
            "INSERT INTO agent_intake_occurrences "
            "(occurrence_id, intake_artifact_id, channel, received_at, occurrence_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.occurrence_id,
                record.intake_artifact_id,
                record.channel,
                record.received_at,
                _canonical_request_json(record.detail),
            ),
        )
        self._record(
            "agent_intake_occurrence", record.occurrence_id, "insert", None, asdict(record)
        )

    def add_intake_extraction(self, record: AgentIntakeExtractionRecord) -> None:
        """Add a canonical machine extraction with its independently checked digest."""
        validate_entity_id(record.extraction_id)
        payload_json = _canonical_request_json(record.payload)
        self.__connection.execute(
            "INSERT INTO agent_intake_extractions "
            "(extraction_id, occurrence_id, extractor, payload_json, payload_digest, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.extraction_id,
                record.occurrence_id,
                record.extractor,
                payload_json,
                _digest(payload_json),
                record.created_at,
            ),
        )
        self._record(
            "agent_intake_extraction", record.extraction_id, "insert", None, asdict(record)
        )

    def add_intake_proposal(self, record: AgentIntakeProposalRecord) -> None:
        """Add an unconfirmed interpretation proposal with revision preconditions."""
        validate_entity_id(record.proposal_id)
        validate_entity_id(record.expected_generation)
        if not isinstance(record.payload, Mapping):
            raise MutationValidationError("Agent intake proposal payload must be a JSON object.")
        payload_json = _canonical_request_json(record.payload)
        self.__connection.execute(
            "INSERT INTO agent_intake_proposals "
            "(proposal_id, extraction_id, policy_version, command_scope, idempotency_key, "
            "expected_generation, expected_revision, payload_json, payload_digest, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.proposal_id,
                record.extraction_id,
                record.policy_version,
                record.command_scope,
                record.idempotency_key,
                record.expected_generation,
                record.expected_revision,
                payload_json,
                _digest(payload_json),
                record.created_at,
            ),
        )
        self._record("agent_intake_proposal", record.proposal_id, "insert", None, asdict(record))

    def add_intake_confirmation(self, record: AgentIntakeConfirmationRecord) -> None:
        """Add explicit confirmation without yet implying application."""
        validate_entity_id(record.confirmation_id)
        self.__connection.execute(
            "INSERT INTO agent_intake_confirmations "
            "(confirmation_id, proposal_id, confirmation_state, actor, confirmation_json, "
            "confirmed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.confirmation_id,
                record.proposal_id,
                record.confirmation_state,
                record.actor,
                _canonical_request_json(record.detail),
                record.confirmed_at,
            ),
        )
        self._record(
            "agent_intake_confirmation", record.confirmation_id, "insert", None, asdict(record)
        )

    def add_intake_application(self, record: AgentIntakeApplicationRecord) -> None:
        """Link only a confirmed proposal to this transaction's changeset."""
        if record.changeset_id != self.changeset_id:
            raise MutationValidationError("Intake application must reference this changeset.")
        self.__connection.execute(
            "INSERT INTO agent_intake_applications "
            "(proposal_id, confirmation_id, changeset_id, applied_at) VALUES (?, ?, ?, ?)",
            (
                record.proposal_id,
                record.confirmation_id,
                record.changeset_id,
                record.applied_at,
            ),
        )
        self._record("agent_intake_application", record.proposal_id, "link", None, asdict(record))

    def _record(
        self,
        entity_kind: str,
        entity_id: str,
        action: str,
        before: Mapping[str, JSONValue] | None,
        after: Mapping[str, JSONValue] | None,
    ) -> None:
        if before is not None:
            _canonical_request_json(before)
        if after is not None:
            _canonical_request_json(after)
        self.__entries.append(_ChangeEntry(entity_kind, entity_id, action, before, after))


def _config_audit_state(revision: ConfigRevisionRecord) -> dict[str, JSONValue]:
    return {
        "artifact_id": revision.artifact_id,
        "parsed_status": revision.parsed_status,
        "parser_version": revision.parser_version,
        "revision_id": revision.revision_id,
    }


_MIGRATED_TRANSACTION_SOURCE_SQL = (
    "SELECT txn.entity_id FROM transactions AS txn "
    "JOIN migration_identities AS identity ON identity.entity_id = txn.entity_id "
    "AND identity.record_kind = 'transaction' "
    "JOIN legacy_payloads AS payload ON payload.provenance_id = txn.provenance_id "
    "JOIN record_provenance AS provenance ON provenance.provenance_id = txn.provenance_id "
    "JOIN observations AS observation ON observation.entity_id = txn.observation_id "
    "AND observation.source_occurrence_id = provenance.source_occurrence_id "
)


def _has_migrated_transaction_source(connection: sqlite3.Connection, transaction_id: str) -> bool:
    """Recognize captured legacy rows whose tag spelling and duplicates were preserved."""
    return (
        connection.execute(
            _MIGRATED_TRANSACTION_SOURCE_SQL + "WHERE txn.entity_id = ?", (transaction_id,)
        ).fetchone()
        is not None
    )


def _parse_preserved_string_array(value: Any) -> list[str]:
    """Decode source-backed legacy arrays without silently normalizing their members."""
    if value is None:
        return []
    try:
        parsed = json.loads(str(value), parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored transaction tags are invalid JSON.") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise RepositoryIntegrityError("Stored legacy transaction tags are not a string array.")
    return parsed


def _parse_string_array(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(str(value), parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored transaction tags are invalid JSON.") from exc
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(parsed) != len(set(parsed))
    ):
        raise RepositoryIntegrityError("Stored transaction tags are not a canonical string array.")
    return parsed


def _manual_transaction_view(current: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Return stable read fields shared by inspection, write, and replay receipts."""
    return {
        "date": current["date_raw"],
        "time": current["time_raw"],
        "datetime": current["datetime_raw"],
        "type_raw": current["type_raw"],
        "type_norm": current["type_norm"],
        "major_raw": current["major_raw"],
        "minor_raw": current["minor_raw"],
        "merchant_raw": current["merchant_raw"],
        "memo_raw": current["memo_raw"],
        "account": current["account_text"],
        "counterparty": current["counterparty"],
        "category_rule": current["category_rule"],
        "tags_rule": current["tags_rule"],
        "tags_ai": current["tags_ai"],
        "amount_exact": current["amount_exact"],
        "currency": current["currency"],
        "is_transfer_candidate": current["is_transfer_candidate"],
        "is_transfer": current["is_transfer"],
        "transfer_group_id": current["transfer_group_id"],
    }


def _manual_audit_state(current: Mapping[str, Any]) -> dict[str, JSONValue]:
    return {
        "category_final": current["category_final"],
        "category_manual": current["category_manual"],
        "confidence_exact": current["confidence_exact"],
        "needs_review": current["needs_review"],
        "notes_manual": current["notes_manual"],
        "tags_final": current["tags_final_audit"],
        "tags_manual": current["tags_manual_audit"],
    }


def _resolve_manual_category(
    category_manual: Any,
    category_rule: Any,
    minor_raw: Any,
    major_raw: Any,
) -> str:
    for candidate in (category_manual, category_rule, minor_raw, major_raw):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return "미분류"


def _exact_equals_integer(
    coefficient: str | None,
    scale: int | None,
    expected: int,
) -> bool:
    if coefficient is None or scale is None:
        return False
    coefficient_value = int(str(coefficient))
    scale_value = int(scale)
    return bool(coefficient_value == expected * 10**scale_value)


def _exact_decimal_text(coefficient: str | None, scale: int | None) -> str | None:
    if coefficient is None or scale is None:
        return None
    negative = coefficient.startswith("-")
    digits = coefficient.removeprefix("-")
    if scale == 0:
        rendered = digits
    elif len(digits) > scale:
        rendered = f"{digits[:-scale]}.{digits[-scale:]}"
    else:
        rendered = f"0.{('0' * (scale - len(digits)))}{digits}"
    return f"-{rendered}" if negative and digits != "0" else rendered


def _require_coverage_target(target: int) -> None:
    if target not in (0, 1):
        raise MutationValidationError("Coverage confidence must be 0 or 1.")


_BULK_TRANSACTION_SQL = (
    "SELECT txn.entity_id, txn.date_raw, txn.time_raw, txn.datetime_raw, txn.timezone_state, "
    "txn.type_raw, txn.type_norm, txn.major_raw, txn.minor_raw, txn.merchant_raw, "
    "txn.memo_raw, txn.notes_manual, txn.account_text, txn.counterparty, txn.category_rule, "
    "txn.category_manual, txn.category_final, txn.tags_rule_json, txn.tags_ai_json, "
    "txn.tags_manual_json, txn.tags_final_json, txn.confidence_value_id, txn.needs_review, "
    "txn.is_transfer_candidate, txn.is_transfer, txn.transfer_group_id, txn.provenance_id, "
    "txn.observation_id, txn.account_id, txn.amount_value_id, amount.coefficient, "
    "amount.scale, amount.lexical, amount.value_kind, amount.origin_kind, "
    "money.currency_code, money.currency_unknown, confidence.coefficient, confidence.scale, "
    "observation.observed_at, observation.effective_at, observation.collected_at, "
    "confidence_number.unit "
    "FROM transactions AS txn "
    "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id "
    "JOIN money_values AS money ON money.value_id = txn.amount_value_id "
    "LEFT JOIN exact_values AS confidence ON confidence.value_id = txn.confidence_value_id "
    "LEFT JOIN number_values AS confidence_number "
    "ON confidence_number.value_id = txn.confidence_value_id "
    "JOIN observations AS observation ON observation.entity_id = txn.observation_id"
)


def _load_bulk_transaction_rows(
    connection: sqlite3.Connection,
    transaction_ids: Sequence[str] | None,
) -> tuple[dict[str, Any], ...]:
    sql, parameters = _bulk_transaction_query(transaction_ids)
    rows = connection.execute(sql, parameters).fetchall()
    if transaction_ids is not None and len(rows) != len(set(transaction_ids)):
        raise MutationValidationError("Transaction identifier was not found.")
    migrated = {row[0] for row in connection.execute(_MIGRATED_TRANSACTION_SOURCE_SQL)}
    return tuple(_bulk_transaction_mapping(row, preserved=row[0] in migrated) for row in rows)


def _bulk_transaction_query(
    transaction_ids: Sequence[str] | None,
) -> tuple[str, tuple[Any, ...]]:
    if transaction_ids is None:
        return f"{_BULK_TRANSACTION_SQL} ORDER BY txn.entity_id", ()
    identifiers = tuple(transaction_ids)
    seen: set[str] = set()
    for transaction_id in identifiers:
        validate_entity_id(transaction_id)
        if transaction_id in seen:
            raise MutationValidationError("Transaction identifiers must be unique.")
        seen.add(transaction_id)
    if not identifiers:
        return f"{_BULK_TRANSACTION_SQL} WHERE 0 ORDER BY txn.entity_id", ()
    placeholders = ", ".join("?" for _ in identifiers)
    sql = f"{_BULK_TRANSACTION_SQL} WHERE txn.entity_id IN ({placeholders}) ORDER BY txn.entity_id"
    return sql, identifiers


def _bulk_transaction_mapping(row: Sequence[Any], *, preserved: bool = False) -> dict[str, Any]:
    coefficient = None if row[37] is None else str(row[37])
    scale = None if row[38] is None else int(row[38])
    amount_coefficient = str(row[30])
    amount_scale = int(row[31])
    mapping = _bulk_transaction_core(row, preserved=preserved)
    mapping.update(_bulk_transaction_amount(row, amount_coefficient, amount_scale))
    mapping.update(
        {
            "confidence_coefficient": coefficient,
            "confidence_exact": _exact_decimal_text(coefficient, scale),
            "confidence_scale": scale,
            "confidence_unit": None if row[42] is None else str(row[42]),
            "collected_at": row[41],
            "effective_at": row[40],
            "observed_at": row[39],
        }
    )
    return mapping


def _bulk_transaction_core(row: Sequence[Any], *, preserved: bool = False) -> dict[str, Any]:
    mapping = _bulk_transaction_identity(row)
    mapping.update(_bulk_transaction_classification(row, preserved=preserved))
    return mapping


def _bulk_transaction_identity(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "account_id": row[28],
        "account_text": row[12],
        "counterparty": row[13],
        "date_raw": row[1],
        "datetime_raw": row[3],
        "observation_id": row[27],
        "provenance_id": row[26],
        "time_raw": row[2],
        "timezone_state": row[4],
        "transaction_id": str(row[0]),
        "type_norm": row[6],
        "type_raw": row[5],
    }


def _bulk_transaction_classification(
    row: Sequence[Any], *, preserved: bool = False
) -> dict[str, Any]:
    parse_tags = _parse_preserved_string_array if preserved else _parse_string_array
    return {
        "category_final": row[16],
        "category_manual": row[15],
        "category_rule": row[14],
        "confidence_value_id": row[21],
        "is_transfer": None if row[24] is None else bool(row[24]),
        "is_transfer_candidate": None if row[23] is None else bool(row[23]),
        "major_raw": row[7],
        "memo_raw": row[10],
        "merchant_raw": row[9],
        "minor_raw": row[8],
        "needs_review": None if row[22] is None else bool(row[22]),
        "notes_manual": row[11],
        "tags_ai": parse_tags(row[18]),
        "tags_final": parse_tags(row[20]),
        "tags_manual": parse_tags(row[19]),
        "tags_rule": parse_tags(row[17]),
        "transfer_group_id": row[25],
    }


def _bulk_transaction_amount(
    row: Sequence[Any],
    amount_coefficient: str,
    amount_scale: int,
) -> dict[str, Any]:
    return {
        "amount_coefficient": amount_coefficient,
        "amount_exact": _exact_decimal_text(amount_coefficient, amount_scale),
        "amount_lexical": None if row[32] is None else str(row[32]),
        "amount_origin_kind": str(row[34]),
        "amount_scale": amount_scale,
        "amount_value_id": row[29],
        "amount_value_kind": str(row[33]),
        "currency": None if row[35] is None else str(row[35]),
        "currency_unknown": bool(row[36]),
    }


def _load_stored_derived_state(
    connection: sqlite3.Connection,
    transaction_id: str,
) -> dict[str, JSONValue]:
    """Load the actual derived columns used for no-op, audit, and stale-before checks."""
    row = connection.execute(
        "SELECT category_final, category_rule, confidence_value_id, needs_review, "
        "tags_final_json, tags_rule_json, is_transfer, is_transfer_candidate, "
        "transfer_group_id FROM transactions WHERE entity_id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Transaction identifier was not found.")
    return _stored_derived_mapping(
        row, preserved=_has_migrated_transaction_source(connection, transaction_id)
    )


def _stored_derived_mapping(row: Sequence[Any], *, preserved: bool = False) -> dict[str, JSONValue]:
    parse_tags = _parse_preserved_string_array if preserved else _parse_string_array
    return {
        "category_final": row[0],
        "category_rule": row[1],
        "confidence_value_id": row[2],
        "is_transfer": None if row[6] is None else bool(row[6]),
        "is_transfer_candidate": None if row[7] is None else bool(row[7]),
        "needs_review": None if row[3] is None else bool(row[3]),
        "tags_final": parse_tags(row[4]),
        "tags_rule": parse_tags(row[5]),
        "transfer_group_id": row[8],
    }


def _reject_stale_derived_before(
    before: Mapping[str, JSONValue],
    stored: Mapping[str, JSONValue],
    after: Mapping[str, JSONValue],
) -> None:
    """Reject caller before-state that does not match the row currently stored."""
    if not isinstance(before, Mapping):
        raise MutationValidationError("Derived before-state is missing a field.")
    for key in after:
        if key not in _DERIVED_COLUMNS:
            raise MutationValidationError("Unsupported derived field.")
        if key not in before:
            raise MutationValidationError("Derived before-state is missing a field.")
    for key, claimed in before.items():
        _reject_mismatched_derived_field(key, claimed, stored)


def _reject_mismatched_derived_field(
    key: str,
    claimed: JSONValue,
    stored: Mapping[str, JSONValue],
) -> None:
    if key not in _DERIVED_COLUMNS:
        raise MutationValidationError("Unsupported derived field.")
    # Before-state is evidence, not a proposed canonical write. The stored tags
    # have already passed the native or source-backed preservation parser.
    if key not in _JSON_DERIVED_KEYS:
        _derived_sql_value(key, claimed)
    actual = _derived_audit_value(key, stored[key])
    if _derived_audit_value(key, claimed) != actual:
        raise MutationValidationError("Derived before-state does not match stored state.")


def _derived_update_parts(
    after: Mapping[str, JSONValue],
    before: Mapping[str, JSONValue],
) -> tuple[list[str], list[Any], dict[str, JSONValue], dict[str, JSONValue]]:
    if not after:
        raise MutationValidationError("Derived state update must include at least one field.")
    unknown = [key for key in after if key not in _DERIVED_COLUMNS]
    if unknown:
        raise MutationValidationError("Unsupported derived field.")
    write = _DerivedWrite()
    for key, value in after.items():
        _append_derived_assignment(write, key, value, before)
    if not write.assignments:
        return [], [], {}, {}
    _canonical_request_json(write.audit_before)
    _canonical_request_json(write.audit_after)
    return write.assignments, write.parameters, write.audit_before, write.audit_after


@dataclass
class _DerivedWrite:
    assignments: list[str] = field(default_factory=list)
    parameters: list[Any] = field(default_factory=list)
    audit_before: dict[str, JSONValue] = field(default_factory=dict)
    audit_after: dict[str, JSONValue] = field(default_factory=dict)


def _append_derived_assignment(
    write: _DerivedWrite,
    key: str,
    value: JSONValue,
    before: Mapping[str, JSONValue],
) -> None:
    if key not in before:
        raise MutationValidationError("Derived before-state is missing a field.")
    sql_value = _derived_sql_value(key, value)
    audit_value = _derived_audit_value(key, value)
    before_value = _derived_audit_value(key, before[key])
    if audit_value == before_value:
        return
    write.assignments.append(f"{_DERIVED_COLUMNS[key]} = ?")
    write.parameters.append(sql_value)
    write.audit_before[key] = before_value
    write.audit_after[key] = audit_value


def _derived_sql_value(key: str, value: JSONValue) -> JSONValue:
    if key in _JSON_DERIVED_KEYS:
        return _derived_tags_sql(value)
    if key in _BOOL_DERIVED_KEYS:
        return _derived_flag_sql(value)
    if key == "confidence_value_id":
        return _derived_confidence_sql(value)
    if value is not None and not isinstance(value, str):
        raise MutationValidationError("Derived text fields must be strings or null.")
    return value


def _derived_tags_sql(value: JSONValue) -> str:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MutationValidationError("Derived tags must be a canonical string array.")
    return _canonical_request_json(value)


def _derived_flag_sql(value: JSONValue) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise MutationValidationError("Derived flags must be boolean or null.")
    return int(value)


def _derived_confidence_sql(value: JSONValue) -> str | None:
    if value is None:
        return None
    validate_entity_id(str(value))
    return str(value)


def _derived_audit_value(key: str, value: JSONValue) -> JSONValue:
    if key in _JSON_DERIVED_KEYS:
        if isinstance(value, list):
            return list(value)
        return _parse_string_array(value)
    if key in _BOOL_DERIVED_KEYS:
        return None if value is None else bool(value)
    return value


class MutationService:
    """Execute typed domain writes, audit, revision, and receipt in one transaction."""

    def __init__(
        self,
        authority_paths: AuthorityPaths,
        activation_evidence: ActivationEvidence,
        *,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
            raise ValueError("Busy timeout must be a non-negative integer.")
        if busy_timeout_ms < 0:
            raise ValueError("Busy timeout must be a non-negative integer.")
        self._authority_paths = authority_paths
        self._activation_evidence = activation_evidence
        self._busy_timeout_ms = busy_timeout_ms

    def execute(self, request: MutationRequest, handler: MutationHandler) -> MutationReceipt:
        """Run one request according to the fixed lock and idempotency ordering contract."""
        with shared_write_lease(
            self._authority_paths,
            timeout_ms=self._busy_timeout_ms,
        ):
            authority = require_repository_binding(
                self._authority_paths,
                self._activation_evidence,
            )
            connection = _connect_writer(authority.paths.database, self._busy_timeout_ms)
            try:
                return self._execute_locked(connection, authority, request, handler)
            finally:
                connection.close()

    def find_replay(self, request: MutationRequest) -> MutationReceipt | None:
        """Return a committed receipt for this exact request without starting a write."""
        with shared_write_lease(
            self._authority_paths,
            timeout_ms=self._busy_timeout_ms,
        ):
            authority = require_repository_binding(
                self._authority_paths,
                self._activation_evidence,
            )
            connection = _connect_reader(authority.paths.database, self._busy_timeout_ms)
            try:
                _validate_locked_repository(connection, authority)
                request_digest = _digest(_canonical_request(request))
                return _lookup_idempotency(connection, request, request_digest)
            finally:
                connection.close()

    def preview(
        self,
        request: MutationRequest,
        handler: MutationHandler,
    ) -> Mapping[str, JSONValue]:
        """Compute a handler result on one pinned read snapshot without publishing state."""
        with shared_write_lease(
            self._authority_paths,
            timeout_ms=self._busy_timeout_ms,
        ):
            authority = require_repository_binding(
                self._authority_paths,
                self._activation_evidence,
            )
            connection = _connect_reader(authority.paths.database, self._busy_timeout_ms)
            try:
                return _preview_locked(connection, authority, request, handler)
            finally:
                connection.close()

    def _execute_locked(
        self,
        connection: sqlite3.Connection,
        authority: RepositoryAuthority,
        request: MutationRequest,
        handler: MutationHandler,
    ) -> MutationReceipt:
        attempt = _AttemptState()
        _begin_writer_transaction(connection)
        try:
            return self._run_started_transaction(
                connection,
                authority,
                request,
                handler,
                attempt,
            )
        except BaseException as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            retained = _attempt_retained_artifacts(attempt)
            if retained:
                raise MutationAbortedError(
                    "Mutation rolled back; immutable source objects were retained.",
                    retained,
                ) from exc
            raise

    def _run_started_transaction(
        self,
        connection: sqlite3.Connection,
        authority: RepositoryAuthority,
        request: MutationRequest,
        handler: MutationHandler,
        attempt: _AttemptState,
    ) -> MutationReceipt:
        if (
            read_activation(self._authority_paths, self._activation_evidence)
            != authority.activation
        ):
            raise RepositoryIntegrityError("Activation changed before the repository write lock.")
        current_revision = _validate_locked_repository(connection, authority)
        request_digest = _digest(_canonical_request(request))
        replay = _lookup_idempotency(connection, request, request_digest)
        if replay is not None:
            connection.execute("ROLLBACK")
            return replay
        _validate_new_request(request, authority, current_revision)
        return _execute_new_request(
            connection,
            _TransactionInputs(
                authority=authority,
                request=request,
                request_digest=request_digest,
                current_revision=current_revision,
                handler=handler,
            ),
            attempt,
        )


def _preview_locked(
    connection: sqlite3.Connection,
    authority: RepositoryAuthority,
    request: MutationRequest,
    handler: MutationHandler,
) -> Mapping[str, JSONValue]:
    _validate_request_shape(request)
    connection.execute("BEGIN")
    try:
        current_revision = _validate_locked_repository(connection, authority)
        _validate_new_request(request, authority, current_revision)
        return _run_preview_handler(connection, authority, handler)
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")


def _run_preview_handler(
    connection: sqlite3.Connection,
    authority: RepositoryAuthority,
    handler: MutationHandler,
) -> Mapping[str, JSONValue]:
    context = MutationContext(connection, authority, _PREVIEW_CHANGESET_ID)
    outcome = handler(context)
    if context.entries:
        raise MutationValidationError("Preview cannot change repository state.")
    if not isinstance(outcome, MutationOutcome):
        raise MutationValidationError("Mutation handler must return MutationOutcome.")
    if not isinstance(outcome.result, Mapping):
        raise MutationValidationError("Mutation result must be a JSON object.")
    _canonical_result_json(outcome.result)
    return outcome.result


def _begin_writer_transaction(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise MutationBusyError("Repository writer lock timed out.") from exc
        raise


def _execute_new_request(
    connection: sqlite3.Connection,
    inputs: _TransactionInputs,
    attempt: _AttemptState,
) -> MutationReceipt:
    request = inputs.request
    created_at = _utc_now()
    connection.execute(
        "INSERT INTO idempotency_requests "
        "(command_scope, idempotency_key, request_digest, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (request.command_scope, request.idempotency_key, inputs.request_digest, created_at),
    )
    changeset_id = new_entity_id()
    context = MutationContext(connection, inputs.authority, changeset_id)
    attempt.context = context
    outcome = inputs.handler(context)
    if not isinstance(outcome, MutationOutcome):
        raise MutationValidationError("Mutation handler must return MutationOutcome.")
    if not isinstance(outcome.result, Mapping):
        raise MutationValidationError("Mutation result must be a JSON object.")
    if any(
        not isinstance(artifact, str) or not artifact for artifact in outcome.retained_artifacts
    ):
        raise MutationValidationError("Retained artifact identities must be non-empty strings.")
    attempt.outcome = outcome
    result_json = _canonical_result_json(outcome.result)
    state_changed = bool(context.entries)
    commit = _CommitState(
        changeset_id=changeset_id,
        base_revision=inputs.current_revision,
        committed_revision=inputs.current_revision + int(state_changed),
        state_changed=state_changed,
        created_at=created_at,
        payload_digest=_digest(_canonical_request_json(request.payload)),
    )
    _insert_changeset(connection, request, commit)
    _insert_change_entries(connection, changeset_id, context.entries)
    _insert_audit_event(connection, request, changeset_id, context.entries, created_at)
    _validate_ownership_assertions(connection)
    _validate_relation_assertions(connection)
    _validate_intake_applications(connection)
    _validate_v3_invariants(connection)
    _validate_v4_invariants(connection)
    _advance_revision(connection, commit)
    retained = _attempt_retained_artifacts(attempt)
    _store_receipt(connection, request, commit, result_json, retained)
    connection.execute("COMMIT")
    return MutationReceipt(
        changeset_id=changeset_id,
        base_revision=commit.base_revision,
        committed_revision=commit.committed_revision,
        state_changed=state_changed,
        result=json.loads(result_json),
        retained_artifacts=retained,
    )


def _advance_revision(connection: sqlite3.Connection, commit: _CommitState) -> None:
    if not commit.state_changed:
        return
    updated = connection.execute(
        "UPDATE repository_meta SET dataset_revision = ? "
        "WHERE singleton = 1 AND dataset_revision = ?",
        (commit.committed_revision, commit.base_revision),
    )
    if updated.rowcount != 1:
        raise MutationConflictError("Dataset revision changed during mutation.")


def _attempt_retained_artifacts(attempt: _AttemptState) -> tuple[str, ...]:
    retained = () if attempt.context is None else attempt.context.retained_artifacts
    if attempt.outcome is not None:
        retained = tuple(dict.fromkeys((*retained, *attempt.outcome.retained_artifacts)))
    return retained


def _connect_writer(database: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    _assert_no_symlink_ancestors(database)
    if database.is_symlink() or not database.is_file():
        raise RepositoryIntegrityError("Active repository is not a regular database file.")
    uri = f"{database.resolve().as_uri()}?mode=rw"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return connection


def _connect_reader(database: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    _assert_no_symlink_ancestors(database)
    if database.is_symlink() or not database.is_file():
        raise RepositoryIntegrityError("Active repository is not a regular database file.")
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=busy_timeout_ms / 1000,
        isolation_level=None,
    )
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return connection


def _validate_locked_repository(
    connection: sqlite3.Connection,
    authority: RepositoryAuthority,
) -> int:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    row = connection.execute(
        "SELECT application_id, schema_version, dataset_generation, dataset_revision "
        "FROM repository_meta WHERE singleton = 1"
    ).fetchone()
    if row is None or application_id != SQLITE_APPLICATION_ID:
        raise RepositoryIntegrityError("Repository identity is invalid under the writer lock.")
    if schema_version != SQLITE_SCHEMA_VERSION or tuple(row[:2]) != (
        application_id,
        schema_version,
    ):
        raise RepositoryIntegrityError("Repository schema is invalid under the writer lock.")
    if str(row[2]) != authority.activation.dataset_generation:
        raise RepositoryIntegrityError("Active generation changed before the mutation.")
    revision = int(row[3])
    if revision < authority.activation.dataset_revision:
        raise RepositoryIntegrityError("Repository revision precedes activation baseline.")
    return revision


def _canonical_request(request: MutationRequest) -> str:
    _validate_request_shape(request)
    return _canonical_request_json(
        {
            "actor": request.actor,
            "command_scope": request.command_scope,
            "confirmation": request.confirmation,
            "expected_generation": request.expected_generation,
            "expected_revision": request.expected_revision,
            "payload": request.payload,
            "reason": request.reason,
            "reversal_of_changeset_id": request.reversal_of_changeset_id,
        }
    )


def _validate_request_shape(request: MutationRequest) -> None:
    if _SCOPE_RE.fullmatch(request.command_scope) is None:
        raise MutationValidationError("Command scope must be a fixed lowercase token.")
    if not request.idempotency_key or len(request.idempotency_key) > _MAX_KEY_LENGTH:
        raise MutationValidationError("Idempotency key is empty or too long.")
    validate_entity_id(request.expected_generation)
    if (
        isinstance(request.expected_revision, bool)
        or not isinstance(request.expected_revision, int)
        or request.expected_revision < 0
    ):
        raise MutationValidationError("Expected revision must be a non-negative integer.")
    if not isinstance(request.actor, str) or not request.actor:
        raise MutationValidationError("Mutation actor must be explicit.")
    if request.reversal_of_changeset_id is not None:
        validate_entity_id(request.reversal_of_changeset_id)
    if not isinstance(request.payload, Mapping):
        raise MutationValidationError("Mutation payload must be a JSON object.")


def _validate_new_request(
    request: MutationRequest,
    authority: RepositoryAuthority,
    current_revision: int,
) -> None:
    if request.expected_generation != authority.activation.dataset_generation:
        raise MutationConflictError("Expected dataset generation is stale.")
    if request.expected_revision != current_revision:
        raise MutationConflictError("Expected dataset revision is stale.")


_SUPPORTED_SOURCE_LINK_KINDS = frozenset({"origin", "duplicate_evidence"})


def _validate_source_link_record(record: TransactionSourceLinkRecord) -> None:
    for identifier in (
        record.link_id,
        record.transaction_id,
        record.provenance_id,
        record.observation_id,
    ):
        validate_entity_id(identifier)
    if record.link_kind not in _SUPPORTED_SOURCE_LINK_KINDS:
        raise MutationValidationError("Source link kind is not supported.")


def _transaction_origin(connection: sqlite3.Connection, transaction_id: str) -> tuple[str, str]:
    row = connection.execute(
        "SELECT provenance_id, observation_id FROM transactions WHERE entity_id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Source link target transaction was not found.")
    return str(row[0]), str(row[1])


def _require_same_source_occurrence(
    connection: sqlite3.Connection,
    provenance_id: str,
    observation_id: str,
) -> None:
    row = connection.execute(
        "SELECT provenance.source_occurrence_id, observation.source_occurrence_id "
        "FROM record_provenance AS provenance "
        "JOIN observations AS observation ON observation.entity_id = ? "
        "WHERE provenance.provenance_id = ?",
        (observation_id, provenance_id),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Source link provenance or observation was not found.")
    if str(row[0]) != str(row[1]):
        raise MutationValidationError(
            "Source link provenance and observation come from different occurrences."
        )


def _validate_origin_source_link(
    connection: sqlite3.Connection,
    record: TransactionSourceLinkRecord,
    origin: tuple[str, str],
) -> None:
    if record.provenance_id != origin[0] or record.observation_id != origin[1]:
        raise MutationValidationError(
            "Origin source link must match the transaction's preserved origin."
        )
    existing = connection.execute(
        "SELECT 1 FROM transaction_source_links "
        "WHERE transaction_id = ? AND link_kind = 'origin' LIMIT 1",
        (record.transaction_id,),
    ).fetchone()
    if existing is not None:
        raise MutationValidationError("A transaction may have at most one origin source link.")


def _reject_reassigned_source_evidence(
    connection: sqlite3.Connection,
    provenance_id: str,
    transaction_id: str,
) -> None:
    claimed = connection.execute(
        "SELECT 1 FROM transaction_source_links WHERE provenance_id = ? "
        "UNION ALL "
        "SELECT 1 FROM transactions WHERE provenance_id = ? AND entity_id <> ? "
        "LIMIT 1",
        (provenance_id, provenance_id, transaction_id),
    ).fetchone()
    if claimed is not None:
        raise MutationValidationError(
            "Source evidence cannot be reassigned to another accepted target."
        )


def _validate_source_link_binding(
    connection: sqlite3.Connection,
    record: TransactionSourceLinkRecord,
) -> None:
    origin = _transaction_origin(connection, record.transaction_id)
    _require_same_source_occurrence(connection, record.provenance_id, record.observation_id)
    _reject_reassigned_source_evidence(connection, record.provenance_id, record.transaction_id)
    if record.link_kind == "origin":
        _validate_origin_source_link(connection, record, origin)
        return
    if record.provenance_id == origin[0]:
        raise MutationValidationError(
            "Duplicate evidence must use a different provenance than the origin."
        )


def _validate_mutation_effective_interval(
    effective_from: str | None,
    effective_to: str | None,
) -> None:
    if not _is_canonical_calendar_date(effective_from) or not _is_canonical_calendar_date(
        effective_to
    ):
        raise MutationValidationError("Effective bounds must be canonical calendar dates.")
    if effective_from is not None and effective_to is not None and effective_to < effective_from:
        raise MutationValidationError("Effective date range is reversed.")


def _lookup_idempotency(
    connection: sqlite3.Connection,
    request: MutationRequest,
    request_digest: str,
) -> MutationReceipt | None:
    row = connection.execute(
        "SELECT request_digest, status, changeset_id, result_json, base_revision, "
        "committed_revision, state_changed FROM idempotency_requests "
        "WHERE command_scope = ? AND idempotency_key = ?",
        (request.command_scope, request.idempotency_key),
    ).fetchone()
    if row is None:
        return None
    if str(row[0]) != request_digest:
        raise MutationConflictError("Idempotency key was already used for another request.")
    if row[1] != "committed":
        raise RepositoryIntegrityError("Published idempotency request is incomplete.")
    envelope = _parse_receipt_envelope(str(row[3]))
    return MutationReceipt(
        changeset_id=str(row[2]),
        base_revision=int(row[4]),
        committed_revision=int(row[5]),
        state_changed=bool(row[6]),
        result=envelope["result"],
        retained_artifacts=tuple(envelope["retained_artifacts"]),
        replayed=True,
    )


def _insert_changeset(
    connection: sqlite3.Connection,
    request: MutationRequest,
    commit: _CommitState,
) -> None:
    confirmation_json = (
        None if request.confirmation is None else _canonical_request_json(request.confirmation)
    )
    connection.execute(
        "INSERT INTO changesets "
        "(changeset_id, command_scope, idempotency_key, payload_digest, "
        "base_revision, committed_revision, "
        "state_changed, actor, reason, confirmation_json, reversal_of_changeset_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            commit.changeset_id,
            request.command_scope,
            request.idempotency_key,
            commit.payload_digest,
            commit.base_revision,
            commit.committed_revision,
            int(commit.state_changed),
            request.actor,
            request.reason,
            confirmation_json,
            request.reversal_of_changeset_id,
            commit.created_at,
        ),
    )


def _insert_change_entries(
    connection: sqlite3.Connection,
    changeset_id: str,
    entries: Sequence[_ChangeEntry],
) -> None:
    for index, entry in enumerate(entries):
        connection.execute(
            "INSERT INTO changeset_entries "
            "(changeset_id, entry_index, entity_kind, entity_id, action, before_json, after_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                changeset_id,
                index,
                entry.entity_kind,
                entry.entity_id,
                entry.action,
                None if entry.before is None else _canonical_request_json(entry.before),
                None if entry.after is None else _canonical_request_json(entry.after),
            ),
        )


def _insert_audit_event(
    connection: sqlite3.Connection,
    request: MutationRequest,
    changeset_id: str,
    entries: Sequence[_ChangeEntry],
    created_at: str,
) -> None:
    event_json = _canonical_request_json(
        {
            "actor": request.actor,
            "changeset_id": changeset_id,
            "command_scope": request.command_scope,
            "entry_count": len(entries),
            "reason": request.reason,
        }
    )
    connection.execute(
        "INSERT INTO audit_events "
        "(audit_event_id, changeset_id, event_kind, event_json, created_at) "
        "VALUES (?, ?, 'mutation_committed', ?, ?)",
        (new_entity_id(), changeset_id, event_json, created_at),
    )


def _store_receipt(
    connection: sqlite3.Connection,
    request: MutationRequest,
    commit: _CommitState,
    result_json: str,
    retained_artifacts: Sequence[str],
) -> None:
    envelope_json = _canonical_result_json(
        {
            "result": json.loads(result_json),
            "retained_artifacts": list(retained_artifacts),
        }
    )
    _parse_receipt_envelope(envelope_json)
    updated = connection.execute(
        "UPDATE idempotency_requests SET status = 'committed', changeset_id = ?, "
        "result_json = ?, base_revision = ?, committed_revision = ?, state_changed = ? "
        "WHERE command_scope = ? AND idempotency_key = ? AND status = 'pending'",
        (
            commit.changeset_id,
            envelope_json,
            commit.base_revision,
            commit.committed_revision,
            int(commit.state_changed),
            request.command_scope,
            request.idempotency_key,
        ),
    )
    if updated.rowcount != 1:
        raise RepositoryIntegrityError("Idempotency receipt reservation was lost.")


def _canonical_request_json(value: JSONValue) -> str:
    _validate_json_tree(value, allow_float=False)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError("Authoritative values must be canonical JSON.") from exc


def _canonical_result_json(value: JSONValue) -> str:
    _validate_json_tree(value, allow_float=True)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError("Mutation result must be finite JSON.") from exc


def _parse_receipt_envelope(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored mutation receipt is invalid JSON.") from exc
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"result", "retained_artifacts"}
        or not isinstance(parsed["result"], dict)
        or not isinstance(parsed["retained_artifacts"], list)
        or any(not isinstance(item, str) or not item for item in parsed["retained_artifacts"])
    ):
        raise RepositoryIntegrityError("Stored mutation receipt envelope is invalid.")
    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


def _validate_json_tree(value: JSONValue, *, allow_float: bool) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not allow_float or not math.isfinite(value):
            raise MutationValidationError(
                "Floating-point request/state values are not authoritative."
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise MutationValidationError("JSON object keys must be strings.")
            _validate_json_tree(item, allow_float=allow_float)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_tree(item, allow_float=allow_float)
        return
    raise MutationValidationError("Value is outside the supported JSON contract.")


def _digest(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
