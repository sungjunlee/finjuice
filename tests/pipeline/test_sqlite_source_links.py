"""Synthetic MutationService tests for schema-v4 transaction source evidence links."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.authority import ActivationEvidence, AuthorityPaths
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    ExactValue,
    IdentifierError,
    MutationValidationError,
    ObservationRecord,
    PartyRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryIntegrityError,
    RepositoryReader,
    SourceObjectStore,
    SourceOccurrenceRecord,
    TransactionRecord,
    TransactionSourceLinkRecord,
    new_entity_id,
    upgrade_repository,
    validate_repository,
)
from finjuice.pipeline.storage.sqlite import schema as schema_module
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationContext,
    MutationOutcome,
    MutationReceipt,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.objects import SourceArtifact

_NOW = "2026-09-09T00:00:00Z"
_SOURCE_BYTES = b"synthetic xlsx bytes for source-link tests"
_LINK_TABLES = ("transaction_source_links", "changeset_entries", "changesets", "audit_events")


@dataclass(frozen=True)
class _ActiveRepository:
    paths: AuthorityPaths
    evidence: ActivationEvidence
    generation: str
    artifact: SourceArtifact
    database: Path

    def service(self) -> MutationService:
        return MutationService(self.paths, self.evidence)

    def request(self, key: str, *, revision: int = 0) -> MutationRequest:
        return MutationRequest(
            command_scope="test.source-links",
            idempotency_key=key,
            payload={"key": key},
            expected_generation=self.generation,
            expected_revision=revision,
            actor="test",
            reason="synthetic",
        )


@dataclass(frozen=True)
class _Ids:
    occurrence: str
    provenance: str
    party: str
    account: str
    observation: str
    amount: str
    confidence: str
    transaction: str
    origin_link: str
    duplicate_occurrence: str
    duplicate_provenance: str
    duplicate_observation: str
    duplicate_link: str


def _evidence() -> ActivationEvidence:
    return ActivationEvidence(
        installed_release_version="0.7.3",
        installed_release_artifact_sha256="a" * 64,
        verified_migration_manifest_sha256="b" * 64,
        verified_pre_cutover_backup_manifest_sha256="c" * 64,
    )


def _write_activation(paths: AuthorityPaths, generation: str) -> None:
    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "activation_schema_version": 1,
        "release_version": "0.7.3",
        "release_artifact_sha256": "a" * 64,
        "dataset_generation": generation,
        "sqlite_schema_version": schema_module.SQLITE_SCHEMA_VERSION,
        "dataset_revision": 0,
        "migration_manifest_sha256": "b" * 64,
        "pre_cutover_backup_manifest_sha256": "c" * 64,
        "activated_at": _NOW,
    }
    paths.activation.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path) -> _ActiveRepository:
    paths = AuthorityPaths(
        control_root=tmp_path / "control",
        generations_root=tmp_path / "generations",
    )
    generation = new_entity_id()
    repository_paths = paths.generation(generation)
    with RepositoryBuilder(repository_paths, generation) as builder:
        artifact = builder.publish_source(io.BytesIO(_SOURCE_BYTES))
        builder.finalize()
    _write_activation(paths, generation)
    return _ActiveRepository(paths, _evidence(), generation, artifact, repository_paths.database)


def _new_ids() -> _Ids:
    return _Ids(*(new_entity_id() for _ in range(13)))


def _query(database: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def _count(database: Path, table: str) -> int:
    return int(_query(database, f"SELECT count(*) FROM {table}")[0][0])  # nosec B608


def _revision(database: Path) -> int:
    return int(_query(database, "SELECT dataset_revision FROM repository_meta")[0][0])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance(provenance_id: str, occurrence_id: str, row: int) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=provenance_id,
        occurrence_id=occurrence_id,
        source_coordinate={"sheet": "synthetic", "row": row},
        legacy_locator={"locator_version": 1, "sheet": "synthetic", "row": row},
        parser_version="test-v1",
    )


def _occurrence(occurrence_id: str, artifact_id: str, name: str) -> SourceOccurrenceRecord:
    return SourceOccurrenceRecord(
        occurrence_id=occurrence_id,
        artifact_id=artifact_id,
        occurrence_kind="banksalad_xlsx",
        original_filename=name,
        imported_at=_NOW,
        parser_version="test-v1",
    )


def _observation(observation_id: str, occurrence_id: str) -> ObservationRecord:
    return ObservationRecord(
        observation_id=observation_id,
        occurrence_id=occurrence_id,
        observed_at=None,
        effective_at="2026-09-01",
        collected_at=_NOW,
        scope_state="partial",
    )


def _origin_link(ids: _Ids) -> TransactionSourceLinkRecord:
    return TransactionSourceLinkRecord(
        link_id=ids.origin_link,
        transaction_id=ids.transaction,
        provenance_id=ids.provenance,
        observation_id=ids.observation,
        link_kind="origin",
    )


def _duplicate_link(ids: _Ids) -> TransactionSourceLinkRecord:
    return TransactionSourceLinkRecord(
        link_id=ids.duplicate_link,
        transaction_id=ids.transaction,
        provenance_id=ids.duplicate_provenance,
        observation_id=ids.duplicate_observation,
        link_kind="duplicate_evidence",
    )


def _write_foundation(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    context.add_source_occurrence(_occurrence(ids.occurrence, artifact_id, "synthetic.xlsx"))
    context.add_provenance(_provenance(ids.provenance, ids.occurrence, row=1))
    context.add_party(PartyRecord(party_id=ids.party, party_kind="person", display_name="P"))
    context.add_account(
        AccountRecord(
            account_id=ids.account,
            account_kind="bank.v1",
            display_name="synthetic account",
            ownership_state="asserted",
            owner_party_id=ids.party,
        )
    )
    context.add_observation(_observation(ids.observation, ids.occurrence))


def _calculated_confidence() -> ExactValue:
    return ExactValue(
        coefficient="1",
        scale=0,
        lexical=None,
        value_kind="number",
        origin_kind="calculated",
        unit="confidence.v1",
    )


def _transaction_record(ids: _Ids, **overrides: Any) -> TransactionRecord:
    fields: dict[str, Any] = {
        "transaction_id": ids.transaction,
        "observation_id": ids.observation,
        "provenance_id": ids.provenance,
        "account_id": ids.account,
        "amount_value_id": ids.amount,
        "date_raw": "2026-09-01",
        "time_raw": "12:00:00",
        "datetime_raw": "2026-09-01 12:00:00",
        "type_raw": "지출",
        "type_norm": "expense",
        "account_text": "synthetic account",
        "merchant_raw": "synthetic cafe",
        "category_final": "food",
        "tags_final_json": '["food"]',
        "confidence_value_id": ids.confidence,
        "needs_review": False,
    }
    fields.update(overrides)
    return TransactionRecord(**fields)


def _write_transaction(context: MutationContext, ids: _Ids) -> None:
    context.add_exact_value(
        ids.amount,
        ExactValue.from_lexical("-1234.50", value_kind="money", currency="KRW"),
        provenance_id=ids.provenance,
    )
    context.add_exact_value(ids.confidence, _calculated_confidence())
    context.add_transaction(_transaction_record(ids))


def _write_duplicate_evidence(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    context.add_source_occurrence(
        _occurrence(ids.duplicate_occurrence, artifact_id, "synthetic-dup.xlsx")
    )
    context.add_provenance(_provenance(ids.duplicate_provenance, ids.duplicate_occurrence, row=2))
    context.add_observation(_observation(ids.duplicate_observation, ids.duplicate_occurrence))


def _write_accepted_transaction(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    _write_foundation(context, artifact_id, ids)
    _write_transaction(context, ids)


def _peer_ids(ids: _Ids) -> _Ids:
    return _Ids(
        **{
            **vars(ids),
            "occurrence": new_entity_id(),
            "provenance": new_entity_id(),
            "observation": new_entity_id(),
            "amount": new_entity_id(),
            "confidence": new_entity_id(),
            "transaction": new_entity_id(),
            "origin_link": new_entity_id(),
            "duplicate_link": new_entity_id(),
        }
    )


def _write_peer_transaction(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    context.add_source_occurrence(_occurrence(ids.occurrence, artifact_id, "peer.xlsx"))
    context.add_provenance(_provenance(ids.provenance, ids.occurrence, row=2))
    context.add_observation(_observation(ids.observation, ids.occurrence))
    _write_transaction(context, ids)


def _retarget_duplicate_link(target: _Ids, origin: _Ids) -> TransactionSourceLinkRecord:
    return TransactionSourceLinkRecord(
        link_id=target.duplicate_link,
        transaction_id=target.transaction,
        provenance_id=origin.provenance,
        observation_id=origin.observation,
        link_kind="duplicate_evidence",
    )


def _later_origin_transaction(ids: _Ids) -> TransactionRecord:
    return _transaction_record(
        ids,
        transaction_id=new_entity_id(),
        observation_id=ids.duplicate_observation,
        provenance_id=ids.duplicate_provenance,
        amount_value_id=new_entity_id(),
        confidence_value_id=new_entity_id(),
        date_raw="2026-09-02",
        datetime_raw="2026-09-02 12:00:00",
        tags_final_json="[]",
    )


def _origin_and_duplicate(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    _write_accepted_transaction(context, artifact_id, ids)
    context.add_transaction_source_link(_origin_link(ids))
    _write_duplicate_evidence(context, artifact_id, ids)
    context.add_transaction_source_link(_duplicate_link(ids))


def test_origin_and_duplicate_links_commit_atomically_with_one_revision(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()

    def handler(context: MutationContext) -> MutationOutcome:
        _origin_and_duplicate(context, repository.artifact.artifact_id, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    receipt = repository.service().execute(repository.request("links-1"), handler)

    assert (receipt.state_changed, receipt.base_revision, receipt.committed_revision) == (
        True,
        0,
        1,
    )
    assert receipt.replayed is False
    database = repository.database
    assert _revision(database) == 1
    assert _count(database, "transaction_source_links") == 2
    assert _count(database, "changesets") == 1
    assert _count(database, "audit_events") == 1
    rows = _query(
        database,
        "SELECT link_id, transaction_id, provenance_id, observation_id, link_kind, "
        "created_changeset_id FROM transaction_source_links ORDER BY link_kind",
    )
    assert rows == [
        (
            ids.duplicate_link,
            ids.transaction,
            ids.duplicate_provenance,
            ids.duplicate_observation,
            "duplicate_evidence",
            receipt.changeset_id,
        ),
        (
            ids.origin_link,
            ids.transaction,
            ids.provenance,
            ids.observation,
            "origin",
            receipt.changeset_id,
        ),
    ]
    actions = _query(
        database,
        "SELECT entity_kind, entity_id, action FROM changeset_entries "
        "WHERE entity_kind = 'transaction_source_link' ORDER BY entry_index",
    )
    assert actions == [
        ("transaction_source_link", ids.origin_link, "link"),
        ("transaction_source_link", ids.duplicate_link, "link"),
    ]
    validate_repository(database)


def test_explicit_replay_returns_same_receipt_without_new_link(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    calls: list[str] = []

    def handler(context: MutationContext) -> MutationOutcome:
        calls.append("run")
        _origin_and_duplicate(context, repository.artifact.artifact_id, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    first = repository.service().execute(repository.request("links-replay"), handler)
    replay = repository.service().execute(repository.request("links-replay"), handler)
    lookup = repository.service().find_replay(repository.request("links-replay"))

    assert calls == ["run"]
    assert replay == MutationReceipt(**{**vars(first), "replayed": True})
    assert lookup == replay
    assert _count(repository.database, "transaction_source_links") == 2
    assert _count(repository.database, "changesets") == 1
    assert _revision(repository.database) == 1


def _assert_mutation_rolled_back(database: Path) -> None:
    for table in ("transactions", *_LINK_TABLES):
        assert _count(database, table) == 0, table
    assert _revision(database) == 0


def test_wrong_target_rolls_back_the_whole_mutation(repository: _ActiveRepository) -> None:
    ids = _new_ids()
    missing = new_entity_id()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=ids.origin_link,
                transaction_id=missing,
                provenance_id=ids.provenance,
                observation_id=ids.observation,
                link_kind="origin",
            )
        )
        return MutationOutcome(result={"transaction_id": ids.transaction})

    with pytest.raises(MutationValidationError, match="was not found"):
        repository.service().execute(repository.request("links-wrong-target"), handler)
    _assert_mutation_rolled_back(repository.database)


def test_mismatched_occurrence_rolls_back_the_whole_mutation(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        _write_duplicate_evidence(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=ids.duplicate_link,
                transaction_id=ids.transaction,
                provenance_id=ids.duplicate_provenance,
                observation_id=ids.observation,
                link_kind="duplicate_evidence",
            )
        )
        return MutationOutcome(result={"transaction_id": ids.transaction})

    with pytest.raises(MutationValidationError, match="different occurrences"):
        repository.service().execute(repository.request("links-mismatch"), handler)
    _assert_mutation_rolled_back(repository.database)


def test_origin_drift_rolls_back_the_whole_mutation(repository: _ActiveRepository) -> None:
    ids = _new_ids()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        _write_duplicate_evidence(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=ids.origin_link,
                transaction_id=ids.transaction,
                provenance_id=ids.duplicate_provenance,
                observation_id=ids.duplicate_observation,
                link_kind="origin",
            )
        )
        return MutationOutcome(result={"transaction_id": ids.transaction})

    with pytest.raises(MutationValidationError, match="preserved origin"):
        repository.service().execute(repository.request("links-drift"), handler)
    _assert_mutation_rolled_back(repository.database)


def test_invalid_link_id_rolls_back_the_whole_mutation(repository: _ActiveRepository) -> None:
    ids = _new_ids()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id="not-a-uuid",
                transaction_id=ids.transaction,
                provenance_id=ids.provenance,
                observation_id=ids.observation,
                link_kind="origin",
            )
        )
        return MutationOutcome(result={"transaction_id": ids.transaction})

    with pytest.raises(IdentifierError, match="canonical UUID"):
        repository.service().execute(repository.request("links-bad-id"), handler)
    _assert_mutation_rolled_back(repository.database)


def test_caught_binding_failure_cannot_publish_invalid_link(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    bad_link = new_entity_id()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        _write_duplicate_evidence(context, repository.artifact.artifact_id, ids)
        with pytest.raises(MutationValidationError, match="different occurrences"):
            context.add_transaction_source_link(
                TransactionSourceLinkRecord(
                    link_id=bad_link,
                    transaction_id=ids.transaction,
                    provenance_id=ids.duplicate_provenance,
                    observation_id=ids.observation,
                    link_kind="duplicate_evidence",
                )
            )
        context.add_transaction_source_link(_origin_link(ids))
        return MutationOutcome(result={"transaction_id": ids.transaction})

    receipt = repository.service().execute(repository.request("links-caught"), handler)

    assert receipt.committed_revision == 1
    database = repository.database
    assert _count(database, "transaction_source_links") == 1
    assert _query(database, "SELECT link_id FROM transaction_source_links") == [(ids.origin_link,)]
    assert _query(
        database,
        "SELECT entity_id FROM changeset_entries WHERE entity_kind = 'transaction_source_link'",
    ) == [(ids.origin_link,)]
    assert _query(database, "PRAGMA foreign_key_check") == []


def test_provenance_cannot_be_retargeted_and_history_is_append_only(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    other = _Ids(
        **{
            **vars(ids),
            "provenance": new_entity_id(),
            "observation": new_entity_id(),
            "amount": new_entity_id(),
            "confidence": new_entity_id(),
            "transaction": new_entity_id(),
            "origin_link": new_entity_id(),
        }
    )

    def first(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(_origin_link(ids))
        return MutationOutcome(result={"transaction_id": ids.transaction})

    repository.service().execute(repository.request("links-first"), first)

    def retarget(context: MutationContext) -> MutationOutcome:
        context.add_provenance(_provenance(other.provenance, ids.occurrence, row=3))
        context.add_observation(_observation(other.observation, ids.occurrence))
        context.add_exact_value(
            other.amount,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=other.provenance,
        )
        context.add_exact_value(other.confidence, _calculated_confidence())
        context.add_transaction(
            _transaction_record(
                other,
                account_id=ids.account,
                date_raw="2026-09-02",
                datetime_raw="2026-09-02 12:00:00",
                tags_final_json="[]",
            )
        )
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=other.origin_link,
                transaction_id=other.transaction,
                provenance_id=ids.provenance,
                observation_id=ids.observation,
                link_kind="duplicate_evidence",
            )
        )
        return MutationOutcome(result={"transaction_id": other.transaction})

    with pytest.raises(MutationValidationError, match="cannot be reassigned"):
        repository.service().execute(repository.request("links-retarget", revision=1), retarget)

    database = repository.database
    assert _count(database, "transaction_source_links") == 1
    assert _count(database, "transactions") == 1
    assert _revision(database) == 1
    connection = sqlite3.connect(database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute(
                "UPDATE transaction_source_links SET link_kind = 'duplicate_evidence' "
                "WHERE link_id = ?",
                (ids.origin_link,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute(
                "DELETE FROM transaction_source_links WHERE link_id = ?",
                (ids.origin_link,),
            )
    finally:
        connection.close()


def test_baseline_origin_without_link_cannot_be_retargeted(
    repository: _ActiveRepository,
) -> None:
    origin = _new_ids()
    target = _peer_ids(origin)

    def first(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, origin)
        return MutationOutcome(result={"transaction_id": origin.transaction})

    repository.service().execute(repository.request("links-baseline-origin"), first)

    def retarget(context: MutationContext) -> MutationOutcome:
        _write_peer_transaction(context, repository.artifact.artifact_id, target)
        context.add_transaction_source_link(_retarget_duplicate_link(target, origin))
        return MutationOutcome(result={"transaction_id": target.transaction})

    with pytest.raises(MutationValidationError, match="cannot be reassigned"):
        repository.service().execute(
            repository.request("links-baseline-retarget", revision=1), retarget
        )

    database = repository.database
    assert _count(database, "transaction_source_links") == 0
    assert _count(database, "transactions") == 1
    assert _revision(database) == 1
    assert _query(database, "SELECT entity_id FROM transactions") == [(origin.transaction,)]


def test_caught_baseline_origin_retarget_leaves_no_invalid_link(
    repository: _ActiveRepository,
) -> None:
    origin = _new_ids()
    target = _peer_ids(origin)

    def first(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, origin)
        return MutationOutcome(result={"transaction_id": origin.transaction})

    repository.service().execute(repository.request("links-caught-baseline"), first)

    def handler(context: MutationContext) -> MutationOutcome:
        _write_peer_transaction(context, repository.artifact.artifact_id, target)
        with pytest.raises(MutationValidationError, match="cannot be reassigned"):
            context.add_transaction_source_link(_retarget_duplicate_link(target, origin))
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=target.origin_link,
                transaction_id=target.transaction,
                provenance_id=target.provenance,
                observation_id=target.observation,
                link_kind="origin",
            )
        )
        return MutationOutcome(result={"transaction_id": target.transaction})

    receipt = repository.service().execute(
        repository.request("links-caught-retarget", revision=1), handler
    )

    database = repository.database
    assert receipt.committed_revision == 2
    assert _count(database, "transaction_source_links") == 1
    assert _query(database, "SELECT link_id, provenance_id FROM transaction_source_links") == [
        (target.origin_link, target.provenance)
    ]
    assert _query(
        database,
        "SELECT entity_id FROM changeset_entries WHERE entity_kind = 'transaction_source_link'",
    ) == [(target.origin_link,)]
    assert _query(database, "PRAGMA foreign_key_check") == []
    validate_repository(database)


def test_duplicate_link_then_origin_transaction_rolls_back_at_finalize(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    later = _later_origin_transaction(ids)

    def handler(context: MutationContext) -> MutationOutcome:
        _write_accepted_transaction(context, repository.artifact.artifact_id, ids)
        _write_duplicate_evidence(context, repository.artifact.artifact_id, ids)
        context.add_transaction_source_link(_duplicate_link(ids))
        context.add_exact_value(
            later.amount_value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=ids.duplicate_provenance,
        )
        context.add_exact_value(later.confidence_value_id, _calculated_confidence())
        context.add_transaction(later)
        return MutationOutcome(result={"transaction_id": later.transaction_id})

    with pytest.raises(RepositoryIntegrityError, match="reassigns another transaction"):
        repository.service().execute(repository.request("links-reverse-origin"), handler)
    _assert_mutation_rolled_back(repository.database)


def _insert_synthetic_changeset(connection: sqlite3.Connection) -> str:
    changeset_id = new_entity_id()
    connection.execute(
        "INSERT INTO changesets ("
        "changeset_id, command_scope, idempotency_key, payload_digest, "
        "base_revision, committed_revision, state_changed, actor, created_at"
        ") VALUES (?, 'test.source-links', 'synthetic', ?, 0, 0, 0, 'test', ?)",
        (changeset_id, "a" * 64, _NOW),
    )
    return changeset_id


def _baseline_transaction_record(
    transaction_id: str,
    observation_id: str,
    provenance_id: str,
    account_id: str,
    amount_id: str,
) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=transaction_id,
        observation_id=observation_id,
        provenance_id=provenance_id,
        account_id=account_id,
        amount_value_id=amount_id,
        date_raw="2026-09-01",
        time_raw="00:00:00",
        datetime_raw="2026-09-01 00:00:00",
        type_raw="expense",
        type_norm="expense",
        account_text="baseline",
        tags_final_json="[]",
    )


def _require_account(builder: RepositoryBuilder, account_id: str | None) -> str:
    if account_id is not None:
        return account_id
    created = new_entity_id()
    builder.add_account(AccountRecord(account_id=created, account_kind="bank.v1"))
    return created


def _add_unlinked_evidence(
    builder: RepositoryBuilder, artifact_id: str, filename: str, row: int
) -> tuple[str, str]:
    occurrence_id = new_entity_id()
    observation_id = new_entity_id()
    provenance_id = new_entity_id()
    builder.add_source_occurrence(_occurrence(occurrence_id, artifact_id, filename))
    builder.add_observation(_observation(observation_id, occurrence_id))
    builder.add_provenance(_provenance(provenance_id, occurrence_id, row=row))
    return observation_id, provenance_id


def _add_unlinked_transaction(
    builder: RepositoryBuilder,
    artifact_id: str,
    *,
    filename: str,
    row: int,
    account_id: str | None = None,
) -> tuple[str, str, str, str]:
    account_id = _require_account(builder, account_id)
    observation_id, provenance_id = _add_unlinked_evidence(builder, artifact_id, filename, row)
    amount_id = new_entity_id()
    transaction_id = new_entity_id()
    builder.add_exact_value(
        amount_id,
        ExactValue.from_lexical("100", value_kind="money", currency="KRW"),
        provenance_id=provenance_id,
    )
    builder.add_transaction(
        _baseline_transaction_record(
            transaction_id, observation_id, provenance_id, account_id, amount_id
        )
    )
    return transaction_id, provenance_id, observation_id, account_id


def test_raw_sql_retarget_of_unlinked_origin_fails_validation(tmp_path: Path) -> None:
    paths = schema_module.GenerationPaths(tmp_path / "raw-retarget")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        artifact = builder.publish_source(io.BytesIO(_SOURCE_BYTES))
        origin_tx, origin_prov, origin_obs, account_id = _add_unlinked_transaction(
            builder, artifact.artifact_id, filename="origin.xlsx", row=1
        )
        target_tx, _, _, _ = _add_unlinked_transaction(
            builder,
            artifact.artifact_id,
            filename="target.xlsx",
            row=2,
            account_id=account_id,
        )
        builder.finalize()

    info = validate_repository(paths.database)
    assert info.schema_version == schema_module.SQLITE_SCHEMA_VERSION
    connection = sqlite3.connect(paths.database)
    try:
        changeset_id = _insert_synthetic_changeset(connection)
        connection.execute(
            "INSERT INTO transaction_source_links "
            "(link_id, transaction_id, provenance_id, observation_id, link_kind, "
            "created_changeset_id) VALUES (?, ?, ?, ?, 'duplicate_evidence', ?)",
            (new_entity_id(), target_tx, origin_prov, origin_obs, changeset_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RepositoryIntegrityError, match="reassigns another transaction"):
        validate_repository(paths.database, scratch_root=tmp_path / "scratch")
    rows = _query(paths.database, "SELECT entity_id FROM transactions ORDER BY entity_id")
    assert rows == sorted([(origin_tx,), (target_tx,)])


def test_finalize_rejects_origin_accepted_after_duplicate_link(tmp_path: Path) -> None:
    paths = schema_module.GenerationPaths(tmp_path / "reverse-finalize")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        artifact = builder.publish_source(io.BytesIO(_SOURCE_BYTES))
        target_tx, _, _, account_id = _add_unlinked_transaction(
            builder, artifact.artifact_id, filename="target.xlsx", row=1
        )
        observation_id, provenance_id = _add_unlinked_evidence(
            builder, artifact.artifact_id, "later.xlsx", 2
        )
        changeset_id = _insert_synthetic_changeset(builder._connection)
        builder._connection.execute(
            "INSERT INTO transaction_source_links "
            "(link_id, transaction_id, provenance_id, observation_id, link_kind, "
            "created_changeset_id) VALUES (?, ?, ?, ?, 'duplicate_evidence', ?)",
            (new_entity_id(), target_tx, provenance_id, observation_id, changeset_id),
        )
        amount_id = new_entity_id()
        builder.add_exact_value(
            amount_id,
            ExactValue.from_lexical("100", value_kind="money", currency="KRW"),
            provenance_id=provenance_id,
        )
        builder.add_transaction(
            _baseline_transaction_record(
                new_entity_id(), observation_id, provenance_id, account_id, amount_id
            )
        )
        with pytest.raises(RepositoryIntegrityError, match="reassigns another transaction"):
            builder.finalize()
    assert not paths.database.exists()


def test_baseline_transactions_without_links_remain_valid(tmp_path: Path) -> None:
    paths = schema_module.GenerationPaths(tmp_path / "baseline")
    generation = new_entity_id()
    with RepositoryBuilder(paths, generation) as builder:
        artifact = builder.publish_source(io.BytesIO(_SOURCE_BYTES))
        occurrence_id = new_entity_id()
        observation_id = new_entity_id()
        provenance_id = new_entity_id()
        account_id = new_entity_id()
        amount_id = new_entity_id()
        transaction_id = new_entity_id()
        builder.add_source_occurrence(_occurrence(occurrence_id, artifact.artifact_id, "base.xlsx"))
        builder.add_account(AccountRecord(account_id=account_id, account_kind="bank.v1"))
        builder.add_observation(_observation(observation_id, occurrence_id))
        builder.add_provenance(_provenance(provenance_id, occurrence_id, row=1))
        builder.add_exact_value(
            amount_id,
            ExactValue.from_lexical("100", value_kind="money", currency="KRW"),
            provenance_id=provenance_id,
        )
        builder.add_transaction(
            TransactionRecord(
                transaction_id=transaction_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                account_id=account_id,
                amount_value_id=amount_id,
                date_raw="2026-09-01",
                time_raw="00:00:00",
                datetime_raw="2026-09-01 00:00:00",
                type_raw="expense",
                type_norm="expense",
                account_text="baseline",
                tags_final_json="[]",
            )
        )
        builder.finalize()

    info = validate_repository(paths.database)
    assert info.schema_version == schema_module.SQLITE_SCHEMA_VERSION
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        assert reader.rows("transaction_source_links") == []
        assert [row["entity_id"] for row in reader.rows("transactions")] == [transaction_id]


def _schema_shape(database: Path) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(database)
    try:
        return connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()


def _apply_supported_source_schema(
    connection: sqlite3.Connection,
    generation: str,
    source_version: int,
) -> None:
    schema_module._apply_schema_v1(connection, generation)
    if source_version >= 2:
        schema_module._apply_schema_v2(connection)
    if source_version >= 3:
        schema_module._apply_schema_v3(connection)


def test_fresh_and_supported_upgrades_agree_and_leave_source_hash_unchanged(
    tmp_path: Path,
) -> None:
    latest = schema_module.SQLITE_SCHEMA_VERSION
    fresh = schema_module.GenerationPaths(tmp_path / "fresh")
    with RepositoryBuilder(fresh, new_entity_id()) as builder:
        builder.finalize()
    fresh_shape = _schema_shape(fresh.database)

    for source_version in range(1, latest):
        source = schema_module.GenerationPaths(tmp_path / f"v{source_version}-source")
        schema_module._prepare_generation_layout(source)
        connection = schema_module._connect_builder(source.database)
        generation = new_entity_id()
        try:
            _apply_supported_source_schema(connection, generation, source_version)
        finally:
            connection.close()
        before_hash = _sha256(source.database)
        destination = schema_module.GenerationPaths(tmp_path / f"v{source_version}-upgraded")
        upgraded = upgrade_repository(source.database, destination)
        assert _sha256(source.database) == before_hash
        assert upgraded.schema_version == latest
        assert _schema_shape(destination.database) == fresh_shape


def _insert_v2_assertion(connection: sqlite3.Connection) -> str:
    account_id = new_entity_id()
    assertion_id = new_entity_id()
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'account')",
        (account_id,),
    )
    connection.execute(
        "INSERT INTO accounts (entity_id, account_kind, ownership_state) "
        "VALUES (?, 'bank.v1', 'unknown')",
        (account_id,),
    )
    connection.execute(
        "INSERT INTO ownership_assertion_sets "
        "(assertion_id, account_id, completeness, unknown_remainder, confirmation_state, "
        "evidence_json) VALUES (?, ?, 'unknown', 1, 'unconfirmed', '{}')",
        (assertion_id, account_id),
    )
    connection.execute("COMMIT")
    return assertion_id


def _insert_config_entities(
    connection: sqlite3.Connection,
    artifact: SourceArtifact,
    occurrence_id: str,
    revision_id: str,
) -> None:
    connection.execute(
        "INSERT INTO source_artifacts "
        "(source_artifact_id, digest_hex, byte_length, object_path) VALUES (?, ?, ?, ?)",
        (artifact.artifact_id, artifact.digest_hex, artifact.byte_length, artifact.relative_path),
    )
    connection.execute(
        "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'source_occurrence')",
        (occurrence_id,),
    )
    connection.execute(
        "INSERT INTO source_occurrences (entity_id, source_artifact_id, occurrence_kind) "
        "VALUES (?, ?, 'config_edit')",
        (occurrence_id, artifact.artifact_id),
    )
    connection.execute(
        "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'config_revision')",
        (revision_id,),
    )


def _insert_v3_config_head(
    paths: schema_module.GenerationPaths,
    connection: sqlite3.Connection,
) -> str:
    artifact = SourceObjectStore(paths).publish(io.BytesIO(b"rules: []\n"))
    occurrence_id = new_entity_id()
    revision_id = new_entity_id()
    connection.execute("BEGIN IMMEDIATE")
    _insert_config_entities(connection, artifact, occurrence_id, revision_id)
    connection.execute(
        "INSERT INTO config_revisions "
        "(entity_id, config_kind, source_artifact_id, source_occurrence_id, parsed_status) "
        "VALUES (?, 'rules', ?, ?, 'parsed')",
        (revision_id, artifact.artifact_id, occurrence_id),
    )
    connection.execute(
        "INSERT INTO config_heads (config_kind, revision_id, updated_at) VALUES ('rules', ?, ?)",
        (revision_id, _NOW),
    )
    connection.execute("COMMIT")
    return revision_id


def test_upgrade_preserves_v2_assertions_and_v3_config_heads(
    tmp_path: Path,
) -> None:
    source = schema_module.GenerationPaths(tmp_path / "v3-active")
    schema_module._prepare_generation_layout(source)
    connection = schema_module._connect_builder(source.database)
    generation = new_entity_id()
    try:
        _apply_supported_source_schema(connection, generation, 3)
        assertion_id = _insert_v2_assertion(connection)
        revision_id = _insert_v3_config_head(source, connection)
    finally:
        connection.close()
    before_hash = _sha256(source.database)
    destination = schema_module.GenerationPaths(tmp_path / "v3-upgraded")

    upgraded = upgrade_repository(source.database, destination)

    assert _sha256(source.database) == before_hash
    assert upgraded.schema_version == schema_module.SQLITE_SCHEMA_VERSION
    validate_repository(destination.database, scratch_root=tmp_path / "scratch")
    with RepositoryReader(destination.database, scratch_root=tmp_path / "scratch") as reader:
        assert [row["assertion_id"] for row in reader.rows("ownership_assertion_sets")] == [
            assertion_id
        ]
        assert reader.rows("config_heads")[0]["revision_id"] == revision_id
        assert reader.rows("transaction_source_links") == []
