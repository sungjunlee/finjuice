"""Single atomic mutation boundary for the active authoritative repository."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

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
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import (
    SourceArtifact,
    SourceObjectStore,
    _assert_no_symlink_ancestors,
)
from finjuice.pipeline.storage.sqlite.records import (
    AgentIntakeApplicationRecord,
    AgentIntakeArtifactRecord,
    AgentIntakeConfirmationRecord,
    AgentIntakeExtractionRecord,
    AgentIntakeOccurrenceRecord,
    AgentIntakeProposalRecord,
    EntityRelationAssertionRecord,
    OwnershipAssertionRecord,
    OwnershipShareRecord,
)
from finjuice.pipeline.storage.sqlite.schema import (
    _OWNERSHIP_SHARE_UNIT,
    SQLITE_APPLICATION_ID,
    SQLITE_SCHEMA_VERSION,
    _is_canonical_calendar_date,
    _validate_intake_applications,
    _validate_ownership_assertions,
    _validate_relation_assertions,
)

JSONValue: TypeAlias = Any
MutationHandler: TypeAlias = Callable[["MutationContext"], "MutationOutcome"]
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_MAX_KEY_LENGTH = 512
_DEFAULT_BUSY_TIMEOUT_MS = 5_000


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
        self.authority = authority
        self.changeset_id = changeset_id
        self.__entries: list[_ChangeEntry] = []
        self.__retained_artifacts: list[str] = []

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

    def add_exact_value(
        self,
        value_id: str,
        value: ExactValue,
        *,
        provenance_id: str | None = None,
    ) -> None:
        """Insert one exact value and semantic subtype without float conversion."""
        validate_entity_id(value_id)
        if provenance_id is not None:
            validate_entity_id(provenance_id)
        self.__connection.execute(
            "INSERT INTO exact_values "
            "(value_id, value_kind, coefficient, scale, lexical, origin_kind, provenance_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                value_id,
                value.value_kind,
                value.coefficient,
                value.scale,
                value.lexical,
                value.origin_kind,
                provenance_id,
            ),
        )
        if value.value_kind == "money":
            self.__connection.execute(
                "INSERT INTO money_values (value_id, currency_code, currency_unknown) "
                "VALUES (?, ?, ?)",
                (value_id, value.currency, int(value.currency_unknown)),
            )
        else:
            table = {
                "quantity": "quantity_values",
                "rate": "rate_values",
                "number": "number_values",
            }[value.value_kind]
            self.__connection.execute(
                f"INSERT INTO {table} (value_id, unit) VALUES (?, ?)",  # nosec B608
                (value_id, value.unit),
            )
        self._record(
            "exact_value",
            value_id,
            "insert",
            None,
            {"value_id": value_id, **asdict(value), "provenance_id": provenance_id},
        )

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
