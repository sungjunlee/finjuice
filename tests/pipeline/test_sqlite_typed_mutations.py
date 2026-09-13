"""Integration tests for typed MutationContext writes through the real MutationService."""

from __future__ import annotations

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
    MutationAbortedError,
    MutationValidationError,
    ObservationRecord,
    PartyRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    SourceOccurrenceRecord,
    TransactionRecord,
    new_entity_id,
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
_ROW_HASH = "same-legacy-row-hash"
_SOURCE_BYTES = b"synthetic xlsx bytes for typed mutation integration"
_TYPED_TABLES = (
    "entities",
    "source_occurrences",
    "record_provenance",
    "exact_values",
    "money_values",
    "number_values",
    "parties",
    "accounts",
    "observations",
    "transactions",
    "legacy_payloads",
    "preservation_issues",
)
_AUDIT_TABLES = ("changesets", "changeset_entries", "audit_events", "idempotency_requests")


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
            command_scope="test.typed",
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
    """Activate an empty synthetic generation with one registered immutable artifact."""
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
    return _Ids(*(new_entity_id() for _ in range(8)))


def _provenance(provenance_id: str, occurrence_id: str, row: int) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=provenance_id,
        occurrence_id=occurrence_id,
        source_coordinate={"sheet": "synthetic", "row": row},
        legacy_locator={
            "locator_version": 1,
            "sheet": "synthetic",
            "row": row,
            "row_hash": _ROW_HASH,
        },
        parser_version="test-v1",
    )


def _transaction(ids: _Ids, **overrides: Any) -> TransactionRecord:
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


def _write_foundation(context: MutationContext, artifact_id: str, ids: _Ids) -> None:
    context.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=ids.occurrence,
            artifact_id=artifact_id,
            occurrence_kind="banksalad_xlsx",
            original_filename="synthetic.xlsx",
            imported_at=_NOW,
            parser_version="test-v1",
        )
    )
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
    context.add_observation(
        ObservationRecord(
            observation_id=ids.observation,
            occurrence_id=ids.occurrence,
            observed_at=None,
            effective_at="2026-09-01",
            collected_at=_NOW,
            scope_state="partial",
        )
    )


def _write_transaction(context: MutationContext, ids: _Ids) -> None:
    context.add_exact_value(
        ids.amount,
        ExactValue.from_lexical("-1234.50", value_kind="money", currency="KRW"),
        provenance_id=ids.provenance,
    )
    context.add_exact_value(
        ids.confidence,
        ExactValue(
            coefficient="1",
            scale=0,
            lexical=None,
            value_kind="number",
            origin_kind="calculated",
            unit="confidence.v1",
        ),
    )
    context.add_transaction(_transaction(ids))


def _expected_entries(ids: _Ids) -> list[tuple[str, str]]:
    return [
        ("source_occurrence", ids.occurrence),
        ("record_provenance", ids.provenance),
        ("party", ids.party),
        ("account", ids.account),
        ("observation", ids.observation),
        ("exact_value", ids.amount),
        ("exact_value", ids.confidence),
        ("transaction", ids.transaction),
    ]


def _query(database: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def _count(database: Path, table: str) -> int:
    assert table in (*_TYPED_TABLES, *_AUDIT_TABLES)
    return int(_query(database, f"SELECT count(*) FROM {table}")[0][0])  # nosec B608


def _revision(database: Path) -> int:
    return int(_query(database, "SELECT dataset_revision FROM repository_meta")[0][0])


def _entries(database: Path) -> list[tuple[Any, ...]]:
    return _query(
        database,
        "SELECT entry_index, entity_kind, entity_id, action, before_json, after_json "
        "FROM changeset_entries ORDER BY entry_index",
    )


def _reject_float(text: str) -> None:
    raise AssertionError(f"audit snapshot contains a float: {text}")


def _assert_no_orphan_entities(database: Path) -> None:
    typed = sum(
        _count(database, table)
        for table in ("source_occurrences", "parties", "accounts", "observations", "transactions")
    )
    assert _count(database, "entities") == typed


def test_typed_foundation_to_transaction_commits_rows_audit_revision_and_receipt(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    payload_id = new_entity_id()
    issue_id = new_entity_id()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_foundation(context, repository.artifact.artifact_id, ids)
        _write_transaction(context, ids)
        assert (
            context.add_legacy_payload(
                ids.provenance,
                {"raw_amount": "-1234.50", "row_hash": _ROW_HASH, "nested": {"z": [1, "x"]}},
                payload_id=payload_id,
            )
            == payload_id
        )
        assert (
            context.add_preservation_issue(
                PreservationIssueRecord(
                    provenance_id=ids.provenance,
                    issue_kind="unsupported_currency",
                    detail={"column": "currency", "seen": "?"},
                    field_name="currency",
                    lexical_value="?",
                    issue_id=issue_id,
                )
            )
            == issue_id
        )
        return MutationOutcome(result={"transaction_id": ids.transaction})

    receipt = repository.service().execute(repository.request("typed-1"), handler)

    assert (receipt.state_changed, receipt.base_revision, receipt.committed_revision) == (
        True,
        0,
        1,
    )
    assert receipt.replayed is False and receipt.retained_artifacts == ()
    assert receipt.result == {"transaction_id": ids.transaction}
    database = repository.database
    assert _revision(database) == 1
    for table in _TYPED_TABLES:
        assert _count(database, table) == (
            5 if table == "entities" else 2 if table == "exact_values" else 1
        ), table
    entries = _entries(database)
    expected = [
        *_expected_entries(ids),
        ("legacy_payload", payload_id),
        ("preservation_issue", issue_id),
    ]
    assert [(row[1], row[2]) for row in entries] == expected
    assert [row[0] for row in entries] == list(range(len(expected)))
    assert {(row[3], row[4]) for row in entries} == {("insert", None)}
    amount_after = json.loads(entries[5][5], parse_float=_reject_float)
    assert (amount_after["lexical"], amount_after["coefficient"], amount_after["scale"]) == (
        "-1234.50",
        "-123450",
        2,
    )
    assert amount_after["provenance_id"] == ids.provenance
    for row in entries:
        json.loads(row[5], parse_float=_reject_float)
    assert json.loads(entries[8][5])["payload"]["nested"] == {"z": [1, "x"]}
    assert _query(
        database, "SELECT lexical FROM exact_values WHERE value_id = ?", (ids.amount,)
    ) == [("-1234.50",)]
    assert _count(database, "changesets") == 1 and _count(database, "audit_events") == 1
    changeset = _query(
        database,
        "SELECT changeset_id, state_changed, base_revision, committed_revision FROM changesets",
    )
    assert changeset == [(receipt.changeset_id, 1, 0, 1)]
    event = json.loads(_query(database, "SELECT event_json FROM audit_events")[0][0])
    assert (event["changeset_id"], event["entry_count"]) == (receipt.changeset_id, len(expected))
    assert _query(database, "SELECT status, changeset_id FROM idempotency_requests") == [
        ("committed", receipt.changeset_id)
    ]


def test_explicit_replay_returns_same_receipt_without_duplicating_typed_rows(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    calls: list[str] = []

    def handler(context: MutationContext) -> MutationOutcome:
        calls.append("run")
        _write_foundation(context, repository.artifact.artifact_id, ids)
        _write_transaction(context, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    first = repository.service().execute(repository.request("typed-replay"), handler)
    replay = repository.service().execute(repository.request("typed-replay"), handler)
    lookup = repository.service().find_replay(repository.request("typed-replay"))

    assert calls == ["run"]
    assert replay == MutationReceipt(**{**vars(first), "replayed": True})
    assert lookup == replay
    database = repository.database
    assert _revision(database) == 1
    assert _count(database, "transactions") == 1 and _count(database, "entities") == 5
    assert _count(database, "changesets") == 1 and _count(database, "changeset_entries") == 8


def test_late_handler_failure_rolls_back_typed_rows_and_audit_but_reports_artifact(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()

    def failing(context: MutationContext) -> MutationOutcome:
        context.register_source_artifact(repository.artifact)
        _write_foundation(context, repository.artifact.artifact_id, ids)
        _write_transaction(context, ids)
        raise RuntimeError("synthetic late failure")

    with pytest.raises(MutationAbortedError) as aborted:
        repository.service().execute(repository.request("typed-fail"), failing)

    assert aborted.value.retained_artifacts == (repository.artifact.artifact_id,)
    assert isinstance(aborted.value.__cause__, RuntimeError)
    database = repository.database
    for table in (*_TYPED_TABLES, *_AUDIT_TABLES):
        assert _count(database, table) == 0, table
    assert _revision(database) == 0
    assert (
        repository.paths.generation(repository.generation).root / repository.artifact.relative_path
    ).is_file()

    def succeeding(context: MutationContext) -> MutationOutcome:
        _write_foundation(context, repository.artifact.artifact_id, ids)
        _write_transaction(context, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    receipt = repository.service().execute(repository.request("typed-fail"), succeeding)
    assert (receipt.replayed, receipt.committed_revision) == (False, 1)
    assert _count(database, "transactions") == 1


def test_same_row_hash_with_distinct_provenance_keeps_both_transactions(
    repository: _ActiveRepository,
) -> None:
    first = _new_ids()
    second = _Ids(
        **{
            **vars(first),
            "provenance": new_entity_id(),
            "amount": new_entity_id(),
            "confidence": new_entity_id(),
            "transaction": new_entity_id(),
        }
    )

    def handler(context: MutationContext) -> MutationOutcome:
        _write_foundation(context, repository.artifact.artifact_id, first)
        context.add_provenance(_provenance(second.provenance, second.occurrence, row=2))
        _write_transaction(context, first)
        _write_transaction(context, second)
        return MutationOutcome(result={"count": 2})

    repository.service().execute(repository.request("typed-hash"), handler)

    database = repository.database
    hashes = _query(
        database,
        "SELECT provenance_id, json_extract(legacy_locator_json, '$.row_hash') "
        "FROM record_provenance ORDER BY provenance_id",
    )
    assert sorted(row[0] for row in hashes) == sorted((first.provenance, second.provenance))
    assert {row[1] for row in hashes} == {_ROW_HASH}
    assert _query(
        database, "SELECT provenance_id FROM transactions ORDER BY provenance_id"
    ) == sorted([(first.provenance,), (second.provenance,)])
    assert _count(database, "changeset_entries") == 12
    _assert_no_orphan_entities(database)


def test_subtype_failure_caught_inside_handler_leaves_no_orphan_and_keeps_valid_writes(
    repository: _ActiveRepository,
) -> None:
    ids = _new_ids()
    bad_party = new_entity_id()
    bad_transaction = new_entity_id()
    bad_payload = new_entity_id()

    def handler(context: MutationContext) -> MutationOutcome:
        _write_foundation(context, repository.artifact.artifact_id, ids)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            context.add_party(PartyRecord(party_id=bad_party, party_kind="invalid"))  # type: ignore[arg-type]
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            context.add_transaction(
                _transaction(ids, transaction_id=bad_transaction, account_id=new_entity_id())
            )
        with pytest.raises(MutationValidationError):
            context.add_legacy_payload(ids.provenance, {"ratio": 0.5}, payload_id=bad_payload)
        _write_transaction(context, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    receipt = repository.service().execute(repository.request("typed-caught"), handler)

    assert receipt.committed_revision == 1
    database = repository.database
    _assert_no_orphan_entities(database)
    assert _count(database, "legacy_payloads") == 0
    assert _count(database, "transactions") == 1
    entity_ids = {row[0] for row in _query(database, "SELECT entity_id FROM entities")}
    assert entity_ids.isdisjoint({bad_party, bad_transaction})
    assert [(row[1], row[2]) for row in _entries(database)] == _expected_entries(ids)
    assert _query(database, "PRAGMA foreign_key_check") == []
