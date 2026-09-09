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
    _apply_schema_v1,
    _apply_schema_v2,
    _cleanup_staging,
    _connect_builder,
    _connect_snapshot,
    _prepare_generation_layout,
    _publish_database,
    _validate_connection,
)
from finjuice.pipeline.storage.sqlite.snapshot import inspection_snapshot

_READ_TABLE_SQL: Final = {
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
    "legacy_payloads": "SELECT * FROM legacy_payloads",
    "preservation_issues": "SELECT * FROM preservation_issues",
    "migration_dispositions": "SELECT * FROM migration_dispositions",
    "legacy_identifiers": "SELECT * FROM legacy_identifiers",
    "legacy_identifier_supersessions": "SELECT * FROM legacy_identifier_supersessions",
    "transactions": "SELECT * FROM transactions",
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

_EXACT_SUBTYPE_INSERT_SQL: Final = {
    "quantity": "INSERT INTO quantity_values (value_id, unit) VALUES (?, ?)",
    "rate": "INSERT INTO rate_values (value_id, unit) VALUES (?, ?)",
    "number": "INSERT INTO number_values (value_id, unit) VALUES (?, ?)",
}

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
    ) -> None:
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
        self._closed = False
        self._published_artifacts: list[SourceArtifact] = []
        try:
            _apply_schema_v1(
                self._connection,
                dataset_generation,
                dataset_revision=dataset_revision,
            )
            _apply_schema_v2(self._connection)
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
        self._insert_entity(record.occurrence_id, "source_occurrence")
        self._connection.execute(
            "INSERT INTO source_occurrences "
            "(entity_id, source_artifact_id, occurrence_kind, original_filename, imported_at, "
            "parser_version, source_schema_version, legacy_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.occurrence_id,
                record.artifact_id,
                record.occurrence_kind,
                record.original_filename,
                record.imported_at,
                record.parser_version,
                record.source_schema_version,
                record.legacy_path,
            ),
        )

    def add_provenance(self, record: ProvenanceRecord) -> None:
        """Add canonical source coordinates and a non-collapsing legacy locator."""
        validate_entity_id(record.provenance_id)
        validate_entity_id(record.occurrence_id)
        source_coordinate_json = _canonical_json(record.source_coordinate)
        legacy_locator_json = canonical_locator(record.legacy_locator)
        self._connection.execute(
            "INSERT INTO record_provenance "
            "(provenance_id, source_occurrence_id, source_coordinate_json, "
            "legacy_locator_json, parser_version, source_schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.provenance_id,
                record.occurrence_id,
                source_coordinate_json,
                legacy_locator_json,
                record.parser_version,
                record.source_schema_version,
            ),
        )

    @_atomic_add
    def add_exact_value(
        self,
        value_id: str,
        value: ExactValue,
        *,
        provenance_id: str | None = None,
    ) -> None:
        """Add a canonical exact value and its required semantic subtype."""
        validate_entity_id(value_id)
        if provenance_id is not None:
            validate_entity_id(provenance_id)
        self._connection.execute(
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
            self._connection.execute(
                "INSERT INTO money_values (value_id, currency_code, currency_unknown) "
                "VALUES (?, ?, ?)",
                (value_id, value.currency, int(value.currency_unknown)),
            )
        else:
            self._connection.execute(
                _EXACT_SUBTYPE_INSERT_SQL[value.value_kind],
                (value_id, value.unit),
            )

    @_atomic_add
    def add_party(self, record: PartyRecord) -> None:
        """Add a party foundation row."""
        self._insert_entity(record.party_id, "party")
        self._connection.execute(
            "INSERT INTO parties (entity_id, party_kind, display_name) VALUES (?, ?, ?)",
            (record.party_id, record.party_kind, record.display_name),
        )

    @_atomic_add
    def add_account(self, record: AccountRecord) -> None:
        """Add an account with explicit ownership state."""
        self._insert_entity(record.account_id, "account")
        self._connection.execute(
            "INSERT INTO accounts "
            "(entity_id, account_kind, display_name, ownership_state, owner_party_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.account_id,
                record.account_kind,
                record.display_name,
                record.ownership_state,
                record.owner_party_id,
            ),
        )

    @_atomic_add
    def add_resource(self, record: ResourceRecord) -> None:
        """Add a resource or instrument foundation row."""
        self._insert_entity(record.resource_id, "resource")
        self._connection.execute(
            "INSERT INTO resources (entity_id, resource_kind, display_name) VALUES (?, ?, ?)",
            (record.resource_id, record.resource_kind, record.display_name),
        )

    @_atomic_add
    def add_observation(self, record: ObservationRecord) -> None:
        """Add source-backed temporal and scope context."""
        self._insert_entity(record.observation_id, "observation")
        self._connection.execute(
            "INSERT INTO observations "
            "(entity_id, source_occurrence_id, observed_at, effective_at, collected_at, "
            "scope_state, confirmation_state, supersedes_observation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.occurrence_id,
                record.observed_at,
                record.effective_at,
                record.collected_at,
                record.scope_state,
                record.confirmation_state,
                record.supersedes_observation_id,
            ),
        )

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

    def add_legacy_payload(
        self,
        provenance_id: str,
        payload: Mapping[str, Any] | Sequence[Any],
        *,
        payload_id: str | None = None,
    ) -> str:
        """Preserve the full legacy payload alongside typed rows."""
        payload_id = payload_id or str(uuid.uuid4())
        validate_entity_id(payload_id)
        validate_entity_id(provenance_id)
        self._connection.execute(
            "INSERT INTO legacy_payloads "
            "(payload_id, provenance_id, payload_json) VALUES (?, ?, ?)",
            (payload_id, provenance_id, _canonical_json(payload)),
        )
        return payload_id

    def add_preservation_issue(self, record: PreservationIssueRecord) -> str:
        """Record a lossless typing or preservation problem without discarding evidence."""
        issue_id = record.issue_id or str(uuid.uuid4())
        validate_entity_id(issue_id)
        validate_entity_id(record.provenance_id)
        self._connection.execute(
            "INSERT INTO preservation_issues "
            "(issue_id, provenance_id, field_name, issue_kind, lexical_value, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                issue_id,
                record.provenance_id,
                record.field_name,
                record.issue_kind,
                record.lexical_value,
                _canonical_json(record.detail),
            ),
        )
        return issue_id

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
        self._insert_entity(record.transaction_id, "transaction")
        self._connection.execute(
            "INSERT INTO transactions "
            "(entity_id, observation_id, provenance_id, account_id, amount_value_id, date_raw, "
            "time_raw, datetime_raw, timezone_state, type_raw, type_norm, major_raw, minor_raw, "
            "merchant_raw, memo_raw, notes_manual, account_text, counterparty, category_rule, "
            "category_manual, category_final, tags_rule_json, tags_ai_json, tags_manual_json, "
            "tags_final_json, confidence_value_id, needs_review, is_transfer_candidate, "
            "is_transfer, transfer_group_id) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?)",
            (
                record.transaction_id,
                record.observation_id,
                record.provenance_id,
                record.account_id,
                record.amount_value_id,
                record.date_raw,
                record.time_raw,
                record.datetime_raw,
                record.timezone_state,
                record.type_raw,
                record.type_norm,
                record.major_raw,
                record.minor_raw,
                record.merchant_raw,
                record.memo_raw,
                record.notes_manual,
                record.account_text,
                record.counterparty,
                record.category_rule,
                record.category_manual,
                record.category_final,
                _canonical_array_text(record.tags_rule_json),
                _canonical_array_text(record.tags_ai_json),
                _canonical_array_text(record.tags_manual_json),
                _canonical_array_text(record.tags_final_json),
                record.confidence_value_id,
                _optional_bool(record.needs_review),
                _optional_bool(record.is_transfer_candidate),
                _optional_bool(record.is_transfer),
                record.transfer_group_id,
            ),
        )

    @_atomic_add
    def add_overview_fact(self, record: OverviewFactRecord) -> None:
        """Add one typed overview fact."""
        self._insert_entity(record.fact_id, "overview_fact")
        self._connection.execute(
            "INSERT INTO overview_facts "
            "(entity_id, observation_id, provenance_id, snapshot_date, sheet_name, block_id, "
            "block_title, fact_kind, row_label, column_label, numeric_value_id, value_text, "
            "value_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.fact_id,
                record.observation_id,
                record.provenance_id,
                record.snapshot_date,
                record.sheet_name,
                record.block_id,
                record.block_title,
                record.fact_kind,
                record.row_label,
                record.column_label,
                record.numeric_value_id,
                record.value_text,
                record.value_type,
            ),
        )

    @_atomic_add
    def add_overview_balance(self, record: OverviewBalanceRecord) -> None:
        """Add a typed overview balance."""
        self._insert_entity(record.balance_id, "overview_balance")
        self._connection.execute(
            "INSERT INTO overview_balances "
            "(entity_id, observation_id, provenance_id, source_fact_id, amount_value_id, "
            "snapshot_date, side, category, item_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.balance_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.amount_value_id,
                record.snapshot_date,
                record.side,
                record.category,
                record.item_name,
            ),
        )

    @_atomic_add
    def add_overview_cashflow(self, record: OverviewCashflowRecord) -> None:
        """Add a typed overview cashflow."""
        self._insert_entity(record.cashflow_id, "overview_cashflow")
        self._connection.execute(
            "INSERT INTO overview_cashflows "
            "(entity_id, observation_id, provenance_id, source_fact_id, amount_value_id, "
            "snapshot_date, period_month, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.cashflow_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.amount_value_id,
                record.snapshot_date,
                record.period_month,
                record.category,
            ),
        )

    @_atomic_add
    def add_overview_insurance(self, record: OverviewInsuranceRecord) -> None:
        """Add a typed overview insurance row."""
        self._insert_entity(record.insurance_id, "overview_insurance")
        self._connection.execute(
            "INSERT INTO overview_insurance "
            "(entity_id, observation_id, provenance_id, source_fact_id, paid_amount_value_id, "
            "snapshot_date, institution, policy_name, contract_status, contract_date, "
            "maturity_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.insurance_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.paid_amount_value_id,
                record.snapshot_date,
                record.institution,
                record.policy_name,
                record.contract_status,
                record.contract_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_overview_investment(self, record: OverviewInvestmentRecord) -> None:
        """Add a typed overview investment row."""
        self._insert_entity(record.investment_id, "overview_investment")
        self._connection.execute(
            "INSERT INTO overview_investments "
            "(entity_id, observation_id, provenance_id, source_fact_id, principal_value_id, "
            "valuation_value_id, return_rate_value_id, snapshot_date, product_type, institution, "
            "product_name, start_date, maturity_date) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.investment_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.principal_value_id,
                record.valuation_value_id,
                record.return_rate_value_id,
                record.snapshot_date,
                record.product_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_overview_loan(self, record: OverviewLoanRecord) -> None:
        """Add a typed overview loan row."""
        self._insert_entity(record.loan_id, "overview_loan")
        self._connection.execute(
            "INSERT INTO overview_loans "
            "(entity_id, observation_id, provenance_id, source_fact_id, principal_value_id, "
            "balance_value_id, interest_rate_value_id, snapshot_date, loan_type, institution, "
            "product_name, start_date, maturity_date) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.loan_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.principal_value_id,
                record.balance_value_id,
                record.interest_rate_value_id,
                record.snapshot_date,
                record.loan_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_asset_snapshot(self, record: AssetSnapshotRecord) -> None:
        """Add a typed asset position snapshot."""
        self._insert_entity(record.snapshot_id, "asset_snapshot")
        self._connection.execute(
            "INSERT INTO asset_snapshots "
            "(entity_id, observation_id, provenance_id, account_id, resource_id, "
            "quantity_value_id, market_value_id, snapshot_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.snapshot_id,
                record.observation_id,
                record.provenance_id,
                record.account_id,
                record.resource_id,
                record.quantity_value_id,
                record.market_value_id,
                record.snapshot_date,
            ),
        )

    def finalize(self) -> RepositoryInfo:
        """Validate, close, and atomically publish the complete candidate database."""
        self._require_open()
        try:
            info = _validate_connection(
                self._connection,
                expected_generation=self.dataset_generation,
                object_paths=self.paths,
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

    def __init__(self, database: Path, *, scratch_root: Path | None = None) -> None:
        self._snapshot_context = inspection_snapshot(database, scratch_root=scratch_root)
        snapshot = self._snapshot_context.__enter__()
        try:
            self._connection = _connect_snapshot(snapshot)
            repository_paths = GenerationPaths(database.expanduser().absolute().parent)
            self.info = _validate_connection(
                self._connection,
                object_paths=repository_paths,
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

    def rows(self, table: str) -> list[dict[str, Any]]:
        """Return rows from one fixed schema table as dictionaries."""
        if self._closed:
            raise RuntimeError("Repository reader is already closed.")
        query = _READ_TABLE_SQL.get(table)
        if query is None:
            raise ValueError("Table is not part of the authoritative repository read surface.")
        cursor = self._connection.execute(query)
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

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


def _canonical_array_text(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Transaction tag fields must contain JSON arrays.") from exc
    if not isinstance(parsed, list):
        raise ValueError("Transaction tag fields must contain JSON arrays.")
    return _canonical_json(parsed)


def _optional_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("Optional flags must be booleans or null.")
    return int(value)
