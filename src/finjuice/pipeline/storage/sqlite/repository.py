"""Isolated staging builder and snapshot reader for authoritative SQLite storage."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Callable, Final, Iterator, TypeVar, cast

from finjuice.pipeline.storage.sqlite.errors import RepositoryPathError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import (
    canonical_locator,
    migration_entity_id,
    validate_entity_id,
)
from finjuice.pipeline.storage.sqlite.legacy_overview import (
    LegacyOverviewBalanceRecord,
    LegacyOverviewCandidateRecord,
    LegacyOverviewCashflowRecord,
    LegacyOverviewInsuranceRecord,
    LegacyOverviewInvestmentRecord,
    LegacyOverviewLoanRecord,
    LegacyOverviewReferenceRecord,
    LegacyOverviewReportRecord,
    LegacyOverviewWriter,
)
from finjuice.pipeline.storage.sqlite.objects import SourceArtifact, SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    AssetSnapshotRecord,
    ConfigRevisionRecord,
    EntityKind,
    LegacyIdentifierRecord,
    MigrationIdentityRecord,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
    PartyRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    ResourceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
)
from finjuice.pipeline.storage.sqlite.schema import (
    RepositoryInfo,
    _cleanup_staging,
    _connect_builder,
    _connect_snapshot,
    _initialize_schema,
    _prepare_generation_layout,
    _publish_database,
    _resolve_schema_version,
    _validate_connection,
)
from finjuice.pipeline.storage.sqlite.schema_v5 import LEGACY_OVERVIEW_TABLES
from finjuice.pipeline.storage.sqlite.snapshot import inspection_snapshot
from finjuice.pipeline.storage.sqlite.status_reads import StatusReadSnapshot, status_snapshot
from finjuice.pipeline.storage.sqlite.transaction_reads import (
    TransactionReadSnapshot,
    transaction_snapshot,
)
from finjuice.pipeline.storage.sqlite.writes import (
    _EXACT_SUBTYPE_INSERT_SQL as _WRITER_EXACT_SUBTYPE_INSERT_SQL,
)
from finjuice.pipeline.storage.sqlite.writes import TypedRowWriter

_READ_TABLE_SQL_V4: Final = {
    "repository_meta": "SELECT * FROM repository_meta",
    "schema_migrations": "SELECT * FROM schema_migrations",
    "entities": "SELECT * FROM entities",
    "migration_identities": "SELECT * FROM migration_identities",
    "source_artifacts": "SELECT * FROM source_artifacts",
    "source_occurrences": "SELECT * FROM source_occurrences",
    "record_provenance": "SELECT * FROM record_provenance",
    "exact_values": "SELECT * FROM exact_values",
    "money_values": "SELECT * FROM money_values",
    "quantity_values": "SELECT * FROM quantity_values",
    "rate_values": "SELECT * FROM rate_values",
    "number_values": "SELECT * FROM number_values",
    "parties": "SELECT * FROM parties",
    "accounts": "SELECT * FROM accounts",
    "resources": "SELECT * FROM resources",
    "observations": "SELECT * FROM observations",
    "config_revisions": "SELECT * FROM config_revisions",
    "config_heads": "SELECT * FROM config_heads",
    "legacy_payloads": "SELECT * FROM legacy_payloads",
    "preservation_issues": "SELECT * FROM preservation_issues",
    "migration_dispositions": "SELECT * FROM migration_dispositions",
    "legacy_identifiers": "SELECT * FROM legacy_identifiers",
    "legacy_identifier_supersessions": "SELECT * FROM legacy_identifier_supersessions",
    "transactions": "SELECT * FROM transactions",
    "transaction_source_links": "SELECT * FROM transaction_source_links",
    "overview_facts": "SELECT * FROM overview_facts",
    "overview_balances": "SELECT * FROM overview_balances",
    "overview_cashflows": "SELECT * FROM overview_cashflows",
    "overview_insurance": "SELECT * FROM overview_insurance",
    "overview_investments": "SELECT * FROM overview_investments",
    "overview_loans": "SELECT * FROM overview_loans",
    "asset_snapshots": "SELECT * FROM asset_snapshots",
    "changesets": "SELECT * FROM changesets",
    "changeset_entries": "SELECT * FROM changeset_entries",
    "audit_events": "SELECT * FROM audit_events",
    "idempotency_requests": "SELECT * FROM idempotency_requests",
    "ownership_assertion_sets": "SELECT * FROM ownership_assertion_sets",
    "ownership_assertion_shares": "SELECT * FROM ownership_assertion_shares",
    "entity_relation_assertions": "SELECT * FROM entity_relation_assertions",
    "agent_intake_artifacts": "SELECT * FROM agent_intake_artifacts",
    "agent_intake_occurrences": "SELECT * FROM agent_intake_occurrences",
    "agent_intake_extractions": "SELECT * FROM agent_intake_extractions",
    "agent_intake_proposals": "SELECT * FROM agent_intake_proposals",
    "agent_intake_confirmations": "SELECT * FROM agent_intake_confirmations",
    "agent_intake_applications": "SELECT * FROM agent_intake_applications",
}


_READ_TABLE_SQL_V5: Final = {
    **_READ_TABLE_SQL_V4,
    **{table: f"SELECT * FROM {table}" for table in LEGACY_OVERVIEW_TABLES},
}


def _read_table_sql(schema_version: int) -> Mapping[str, str]:
    """Return exactly the authoritative table surface of the selected schema."""
    _resolve_schema_version(schema_version)
    return {4: _READ_TABLE_SQL_V4, 5: _READ_TABLE_SQL_V5}[schema_version]


# Shared with TypedRowWriter so builder exact-value SQL has exactly one definition.
_EXACT_SUBTYPE_INSERT_SQL: Final = _WRITER_EXACT_SUBTYPE_INSERT_SQL

_Method = TypeVar("_Method", bound=Callable[..., Any])


def _atomic_add(method: _Method) -> _Method:
    """Wrap one builder add call in a rollback-on-error savepoint."""

    @wraps(method)
    def wrapped(self: RepositoryBuilder, *args: Any, **kwargs: Any) -> Any:
        with self._savepoint():
            return method(self, *args, **kwargs)

    return cast(_Method, wrapped)


class RepositoryBuilder:
    """Build one unpublished repository and atomically publish it after validation.

    The connection always points at a randomly named staging file. Published repository files
    are never opened for writes by this API. Call :meth:`finalize` exactly once to make the
    candidate visible at ``GenerationPaths.database``.
    """

    def __init__(
        self,
        paths: GenerationPaths,
        dataset_generation: str,
        dataset_revision: int = 0,
        *,
        expected_schema_version: int | None = None,
    ) -> None:
        self._schema_version = _resolve_schema_version(expected_schema_version)
        validate_entity_id(dataset_generation)
        if isinstance(dataset_revision, bool) or not isinstance(dataset_revision, int):
            raise ValueError("Dataset revision must be the integer zero for a new repository.")
        if dataset_revision != 0:
            raise ValueError("Dataset revision must be zero for a new repository.")
        _prepare_generation_layout(paths)
        if paths.database.exists() or paths.database.is_symlink():
            raise RepositoryPathError(
                "Repository database already exists and will not be replaced."
            )

        self.paths = paths
        self.dataset_generation = dataset_generation
        self.dataset_revision = dataset_revision
        self._staging = paths.root / f".finjuice-sqlite-staging-{uuid.uuid4().hex}"
        self._connection = _connect_builder(self._staging)
        self._writer = TypedRowWriter(self._connection)
        self._closed = False
        self._published_artifacts: list[SourceArtifact] = []
        try:
            _initialize_schema(
                self._connection,
                dataset_generation,
                dataset_revision=dataset_revision,
                schema_version=self._schema_version,
            )
        except Exception:
            self._connection.close()
            self._closed = True
            _cleanup_staging(self._staging)
            raise

    def __enter__(self) -> "RepositoryBuilder":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._closed:
            self.abort()

    def publish_source_path(self, source: Path) -> SourceArtifact:
        """Publish source bytes and register their verified content identity."""
        self._require_open()
        artifact = SourceObjectStore(self.paths).publish_path(source)
        self._published_artifacts.append(artifact)
        self.register_artifact(artifact)
        return artifact

    def publish_source(self, source: BinaryIO) -> SourceArtifact:
        """Publish a binary stream and register its verified content identity."""
        self._require_open()
        artifact = SourceObjectStore(self.paths).publish(source)
        self._published_artifacts.append(artifact)
        self.register_artifact(artifact)
        return artifact

    @property
    def published_artifacts(self) -> tuple[SourceArtifact, ...]:
        """Return receipts for objects this builder published, including after abort."""
        return tuple(self._published_artifacts)

    def register_artifact(self, artifact: SourceArtifact) -> None:
        """Register an object only after re-verifying its path, digest, and length."""
        self._require_open()
        verified = SourceObjectStore(self.paths).verify(
            artifact.artifact_id,
            expected_size=artifact.byte_length,
        )
        if (
            verified.digest_hex != artifact.digest_hex
            or verified.relative_path != artifact.relative_path
        ):
            raise ValueError("Source artifact metadata does not match its immutable object.")
        self._connection.execute(
            "INSERT OR IGNORE INTO source_artifacts "
            "(source_artifact_id, digest_hex, byte_length, object_path) VALUES (?, ?, ?, ?)",
            (
                verified.artifact_id,
                verified.digest_hex,
                verified.byte_length,
                verified.relative_path,
            ),
        )

    @_atomic_add
    def add_source_occurrence(self, record: SourceOccurrenceRecord) -> None:
        """Add a distinct source occurrence, even when source bytes are reused."""
        self._writer.add_source_occurrence(record)

    @_atomic_add
    def add_provenance(self, record: ProvenanceRecord) -> None:
        """Add canonical source coordinates and a non-collapsing legacy locator."""
        self._writer.add_provenance(record)

    @_atomic_add
    def add_exact_value(
        self,
        value_id: str,
        value: ExactValue,
        *,
        provenance_id: str | None = None,
    ) -> None:
        """Add a canonical exact value and its required semantic subtype."""
        self._writer.add_exact_value(value_id, value, provenance_id=provenance_id)

    @_atomic_add
    def add_legacy_overview_report(self, record: LegacyOverviewReportRecord) -> None:
        """Preserve legacy report evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_report(record)

    @_atomic_add
    def add_legacy_overview_balance(self, record: LegacyOverviewBalanceRecord) -> None:
        """Preserve legacy balance evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_balance(record)

    @_atomic_add
    def add_legacy_overview_cashflow(self, record: LegacyOverviewCashflowRecord) -> None:
        """Preserve legacy cashflow evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_cashflow(record)

    @_atomic_add
    def add_legacy_overview_insurance(self, record: LegacyOverviewInsuranceRecord) -> None:
        """Preserve legacy insurance evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_insurance(record)

    @_atomic_add
    def add_legacy_overview_investment(self, record: LegacyOverviewInvestmentRecord) -> None:
        """Preserve legacy investment evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_investment(record)

    @_atomic_add
    def add_legacy_overview_loan(self, record: LegacyOverviewLoanRecord) -> None:
        """Preserve legacy loan evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_loan(record)

    @_atomic_add
    def add_legacy_overview_reference(self, record: LegacyOverviewReferenceRecord) -> None:
        """Preserve legacy reference evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_reference(record)

    @_atomic_add
    def add_legacy_overview_candidate(self, record: LegacyOverviewCandidateRecord) -> None:
        """Preserve legacy candidate evidence in schema v5."""
        LegacyOverviewWriter(self._connection).add_candidate(record)

    @_atomic_add
    def add_party(self, record: PartyRecord) -> None:
        """Add a party foundation row."""
        self._writer.add_party(record)

    @_atomic_add
    def add_account(self, record: AccountRecord) -> None:
        """Add an account with explicit ownership state."""
        self._writer.add_account(record)

    @_atomic_add
    def add_resource(self, record: ResourceRecord) -> None:
        """Add a resource or instrument foundation row."""
        self._writer.add_resource(record)

    @_atomic_add
    def add_observation(self, record: ObservationRecord) -> None:
        """Add source-backed temporal and scope context."""
        self._writer.add_observation(record)

    @_atomic_add
    def add_config_revision(self, record: ConfigRevisionRecord) -> None:
        """Add an immutable source-backed configuration revision."""
        self._insert_entity(record.revision_id, "config_revision")
        payload = (
            None if record.canonical_payload is None else _canonical_json(record.canonical_payload)
        )
        self._connection.execute(
            "INSERT INTO config_revisions "
            "(entity_id, config_kind, source_artifact_id, source_occurrence_id, parsed_status, "
            "parser_version, canonical_payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.revision_id,
                record.config_kind,
                record.artifact_id,
                record.occurrence_id,
                record.parsed_status,
                record.parser_version,
                payload,
            ),
        )

    def set_config_head(self, config_kind: str, revision_id: str, *, updated_at: str) -> None:
        """Select the canonical baseline revision for one configuration domain."""
        validate_entity_id(revision_id)
        row = self._connection.execute(
            "SELECT config_kind FROM config_revisions WHERE entity_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None or str(row[0]) != config_kind:
            raise ValueError("Config head must reference a revision of the same kind.")
        self._connection.execute(
            "INSERT INTO config_heads "
            "(config_kind, revision_id, updated_changeset_id, updated_at) "
            "VALUES (?, ?, NULL, ?)",
            (config_kind, revision_id, updated_at),
        )

    @_atomic_add
    def add_legacy_payload(
        self,
        provenance_id: str,
        payload: Mapping[str, Any] | Sequence[Any],
        *,
        payload_id: str | None = None,
    ) -> str:
        """Preserve the full legacy payload alongside typed rows."""
        return self._writer.add_legacy_payload(provenance_id, payload, payload_id=payload_id)

    @_atomic_add
    def add_preservation_issue(self, record: PreservationIssueRecord) -> str:
        """Record a lossless typing or preservation problem without discarding evidence."""
        return self._writer.add_preservation_issue(record)

    def add_migration_disposition(
        self,
        provenance_id: str,
        disposition: str,
        reason: str,
    ) -> None:
        """Record how one legacy occurrence was handled."""
        validate_entity_id(provenance_id)
        self._connection.execute(
            "INSERT INTO migration_dispositions (provenance_id, disposition, reason) "
            "VALUES (?, ?, ?)",
            (provenance_id, disposition, reason),
        )

    def add_legacy_identifier(self, record: LegacyIdentifierRecord) -> str:
        """Append a captured legacy identifier mapping."""
        mapping_id = record.mapping_id or str(uuid.uuid4())
        validate_entity_id(mapping_id)
        validate_entity_id(record.entity_id)
        if record.provenance_id is not None:
            validate_entity_id(record.provenance_id)
        self._connection.execute(
            "INSERT INTO legacy_identifiers "
            "(mapping_id, entity_id, identifier_kind, identifier_value, provenance_id, "
            "capture_manifest_digest) VALUES (?, ?, ?, ?, ?, ?)",
            (
                mapping_id,
                record.entity_id,
                record.identifier_kind,
                record.identifier_value,
                record.provenance_id,
                record.capture_manifest_digest.removeprefix("sha256:"),
            ),
        )
        return mapping_id

    @_atomic_add
    def add_migration_identity(self, record: MigrationIdentityRecord) -> None:
        """Persist and verify the frozen derivation inputs for one UUIDv5 entity."""
        validate_entity_id(record.entity_id)
        locator_json = canonical_locator(record.legacy_locator)
        derived_id = migration_entity_id(
            record.capture_manifest_digest,
            record.record_kind,
            record.legacy_locator,
        )
        if derived_id != record.entity_id:
            raise ValueError("Migration identity inputs do not derive the entity ID.")
        self._connection.execute(
            "INSERT INTO migration_identities "
            "(entity_id, capture_manifest_digest, record_kind, canonical_locator_json) "
            "VALUES (?, ?, ?, ?)",
            (
                record.entity_id,
                record.capture_manifest_digest.removeprefix("sha256:"),
                record.record_kind,
                locator_json,
            ),
        )

    def supersede_legacy_identifier(
        self,
        previous_mapping_id: str,
        replacement_mapping_id: str,
        reason: str,
        *,
        supersession_id: str | None = None,
    ) -> str:
        """Append an explicit correction edge without rewriting either mapping."""
        supersession_id = supersession_id or str(uuid.uuid4())
        for value in (supersession_id, previous_mapping_id, replacement_mapping_id):
            validate_entity_id(value)
        self._connection.execute(
            "INSERT INTO legacy_identifier_supersessions "
            "(supersession_id, previous_mapping_id, replacement_mapping_id, reason) "
            "VALUES (?, ?, ?, ?)",
            (supersession_id, previous_mapping_id, replacement_mapping_id, reason),
        )
        return supersession_id

    @_atomic_add
    def add_transaction(self, record: TransactionRecord) -> None:
        """Add a typed transaction without collapsing equal row hashes."""
        self._writer.add_transaction(record)

    @_atomic_add
    def add_overview_fact(self, record: OverviewFactRecord) -> None:
        """Add one typed overview fact."""
        self._writer.add_overview_fact(record)

    @_atomic_add
    def add_overview_balance(self, record: OverviewBalanceRecord) -> None:
        """Add a typed overview balance."""
        self._writer.add_overview_balance(record)

    @_atomic_add
    def add_overview_cashflow(self, record: OverviewCashflowRecord) -> None:
        """Add a typed overview cashflow."""
        self._writer.add_overview_cashflow(record)

    @_atomic_add
    def add_overview_insurance(self, record: OverviewInsuranceRecord) -> None:
        """Add a typed overview insurance row."""
        self._writer.add_overview_insurance(record)

    @_atomic_add
    def add_overview_investment(self, record: OverviewInvestmentRecord) -> None:
        """Add a typed overview investment row."""
        self._writer.add_overview_investment(record)

    @_atomic_add
    def add_overview_loan(self, record: OverviewLoanRecord) -> None:
        """Add a typed overview loan row."""
        self._writer.add_overview_loan(record)

    @_atomic_add
    def add_asset_snapshot(self, record: AssetSnapshotRecord) -> None:
        """Add a typed asset position snapshot."""
        self._writer.add_asset_snapshot(record)

    def finalize(self) -> RepositoryInfo:
        """Validate, close, and atomically publish the complete candidate database."""
        self._require_open()
        try:
            info = _validate_connection(
                self._connection,
                expected_generation=self.dataset_generation,
                object_paths=self.paths,
                expected_schema_version=self._schema_version,
            )
        except Exception:
            self.abort()
            raise
        self._connection.close()
        self._closed = True
        _publish_database(self._staging, self.paths.database)
        return info

    def abort(self) -> tuple[SourceArtifact, ...]:
        """Discard the staging DB while preserving and reporting published source objects."""
        if self._closed:
            return self.published_artifacts
        self._connection.close()
        self._closed = True
        _cleanup_staging(self._staging)
        return self.published_artifacts

    @contextmanager
    def _savepoint(self) -> Iterator[None]:
        self._require_open()
        self._connection.execute("SAVEPOINT builder_add")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK TO builder_add")
            self._connection.execute("RELEASE builder_add")
            raise
        else:
            self._connection.execute("RELEASE builder_add")

    def _insert_entity(self, entity_id: str, entity_kind: EntityKind) -> None:
        self._require_open()
        validate_entity_id(entity_id)
        self._connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, ?)",
            (entity_id, entity_kind),
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Repository builder is already closed.")


class RepositoryReader(AbstractContextManager["RepositoryReader"]):
    """Read a stable DB/WAL snapshot without touching source SQLite sidecars."""

    def __init__(
        self,
        database: Path,
        *,
        scratch_root: Path | None = None,
        expected_schema_version: int | None = None,
    ) -> None:
        schema_version = _resolve_schema_version(expected_schema_version)
        self._read_table_sql = _read_table_sql(schema_version)
        self._snapshot_context = inspection_snapshot(database, scratch_root=scratch_root)
        snapshot = self._snapshot_context.__enter__()
        try:
            self._connection = _connect_snapshot(snapshot)
            repository_paths = GenerationPaths(database.expanduser().absolute().parent)
            self._repository_paths = repository_paths
            self.info = _validate_connection(
                self._connection,
                object_paths=repository_paths,
                expected_schema_version=schema_version,
            )
        except Exception:
            self._snapshot_context.__exit__(None, None, None)
            raise
        self._closed = False

    def __enter__(self) -> "RepositoryReader":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def table_names(self) -> tuple[str, ...]:
        """Return the authoritative tables for this reader's exact schema."""
        return tuple(self._read_table_sql)

    def rows(self, table: str) -> list[dict[str, Any]]:
        """Return rows from one fixed schema table as dictionaries."""
        if self._closed:
            raise RuntimeError("Repository reader is already closed.")
        query = self._read_table_sql.get(table)
        if query is None:
            raise ValueError("Table is not part of the authoritative repository read surface.")
        cursor = self._connection.execute(query)
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def transaction_snapshot(self) -> TransactionReadSnapshot:
        """Return exact transaction rows and rules pinned to this reader snapshot."""
        if self._closed:
            raise RuntimeError("Repository reader is already closed.")
        return transaction_snapshot(self._connection, self.info, self._repository_paths)

    def status_snapshot(self) -> StatusReadSnapshot:
        """Return status evidence from the same validated transaction snapshot."""
        transactions = self.transaction_snapshot()
        return status_snapshot(self._connection, self._repository_paths, transactions)

    def close(self) -> None:
        """Close the scratch connection and delete its temporary snapshot."""
        if self._closed:
            return
        self._connection.close()
        self._snapshot_context.__exit__(None, None, None)
        self._closed = True


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Preserved JSON values must have a canonical finite encoding.") from exc
