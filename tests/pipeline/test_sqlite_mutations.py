"""Focused synthetic tests for SQLite authority and atomic mutations."""

from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import sqlite3
import threading
from pathlib import Path
from typing import Any, Literal

import jsonschema
import pytest

from finjuice.pipeline.cli.commands.budget import _budget_edit_transform
from finjuice.pipeline.cli.commands.rules_cmd.mutations import (
    RuleAddRequest,
    _compute_add_rule,
    _compute_remove_rule,
)
from finjuice.pipeline.cli.commands.tag_edit import TagEditRequest, _compute_tag_edit
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage import authority as authority_module
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityDispatch,
    AuthorityPaths,
    LegacyAuthority,
    RepositoryAuthority,
    exclusive_maintenance_lease,
    require_legacy_authority,
    require_repository_authority,
    resolve_authority,
    shared_write_lease,
)
from finjuice.pipeline.storage.mutation_facade import (
    ConfigDocument,
    ConfigMutation,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    AgentIntakeApplicationRecord,
    AgentIntakeArtifactRecord,
    AgentIntakeConfirmationRecord,
    AgentIntakeExtractionRecord,
    AgentIntakeOccurrenceRecord,
    AgentIntakeProposalRecord,
    ConfigRevisionRecord,
    EntityRelationAssertionRecord,
    ExactValue,
    LegacyIdentifierRecord,
    MutationAbortedError,
    MutationConflictError,
    MutationValidationError,
    ObservationRecord,
    OwnershipAssertionRecord,
    OwnershipShareRecord,
    PartyRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryIntegrityError,
    SourceObjectStore,
    SourceOccurrenceRecord,
    TransactionRecord,
    inspect_repository,
    new_entity_id,
    upgrade_repository,
    validate_repository,
)
from finjuice.pipeline.storage.sqlite import mutations as mutation_module
from finjuice.pipeline.storage.sqlite import schema as schema_module
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityConflictError,
    AuthorityIntegrityError,
)
from finjuice.pipeline.storage.sqlite.mutations import (
    ConfigRevisionMutation,
    ManualTransactionEdit,
    MutationOutcome,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

_NOW = "2026-09-09T00:00:00Z"


def _evidence() -> ActivationEvidence:
    return ActivationEvidence(
        installed_release_version="0.7.3",
        installed_release_artifact_sha256="a" * 64,
        verified_migration_manifest_sha256="b" * 64,
        verified_pre_cutover_backup_manifest_sha256="c" * 64,
    )


def _activation_payload(generation: str, *, revision: int = 0) -> dict[str, Any]:
    return {
        "activation_schema_version": 1,
        "release_version": "0.7.3",
        "release_artifact_sha256": "a" * 64,
        "dataset_generation": generation,
        "sqlite_schema_version": schema_module.SQLITE_SCHEMA_VERSION,
        "dataset_revision": revision,
        "migration_manifest_sha256": "b" * 64,
        "pre_cutover_backup_manifest_sha256": "c" * 64,
        "activated_at": _NOW,
    }


def _write_activation(paths: AuthorityPaths, generation: str, *, revision: int = 0) -> None:
    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.activation.write_text(
        json.dumps(_activation_payload(generation, revision=revision)),
        encoding="utf-8",
    )


def _active_repository(
    tmp_path: Path,
    *,
    accounts: int = 3,
    with_artifact: bool = False,
) -> tuple[AuthorityPaths, ActivationEvidence, str, list[str], list[str], str | None]:
    authority_paths = AuthorityPaths(
        control_root=tmp_path / "control",
        generations_root=tmp_path / "generations",
    )
    generation = new_entity_id()
    repository_paths = authority_paths.generation(generation)
    party_ids = [new_entity_id() for _ in range(accounts)]
    account_ids = [new_entity_id() for _ in range(accounts)]
    artifact_id: str | None = None
    with RepositoryBuilder(repository_paths, generation) as builder:
        for party_id, account_id in zip(party_ids, account_ids, strict=True):
            builder.add_party(PartyRecord(party_id=party_id, party_kind="person"))
            builder.add_account(AccountRecord(account_id=account_id, account_kind="bank.v1"))
        if with_artifact:
            artifact_id = builder.publish_source(io.BytesIO(b"intake evidence")).artifact_id
        builder.finalize()
    _write_activation(authority_paths, generation)
    return authority_paths, _evidence(), generation, party_ids, account_ids, artifact_id


def _active_repository_with_transactions(
    tmp_path: Path,
    *,
    row_hashes: tuple[str, ...] = ("legacy-row",),
    nullable_classification: bool = False,
) -> tuple[AuthorityPaths, ActivationEvidence, str, list[str], list[str]]:
    authority_paths = AuthorityPaths(
        control_root=tmp_path / "control",
        generations_root=tmp_path / "generations",
    )
    generation = new_entity_id()
    repository_paths = authority_paths.generation(generation)
    transaction_ids: list[str] = []
    amount_ids: list[str] = []
    with RepositoryBuilder(repository_paths, generation) as builder:
        artifact = builder.publish_source(io.BytesIO(b"synthetic transaction source"))
        occurrence_id = new_entity_id()
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="synthetic",
                original_filename="transactions.csv",
                imported_at=_NOW,
            )
        )
        for index, row_hash in enumerate(row_hashes, start=1):
            account_id = new_entity_id()
            observation_id = new_entity_id()
            provenance_id = new_entity_id()
            transaction_id = new_entity_id()
            amount_id = new_entity_id()
            confidence_id = new_entity_id()
            builder.add_account(AccountRecord(account_id=account_id, account_kind="bank.v1"))
            builder.add_observation(
                ObservationRecord(
                    observation_id=observation_id,
                    occurrence_id=occurrence_id,
                    observed_at=None,
                    effective_at=f"2026-09-{index:02d}",
                    collected_at=_NOW,
                    scope_state="partial",
                )
            )
            builder.add_provenance(
                ProvenanceRecord(
                    provenance_id=provenance_id,
                    occurrence_id=occurrence_id,
                    source_coordinate={"row": index},
                    legacy_locator={"sheet": "transactions", "row": index},
                )
            )
            builder.add_exact_value(
                amount_id,
                ExactValue.from_lexical(
                    str(index * 1000),
                    value_kind="money",
                    currency="KRW",
                ),
                provenance_id=provenance_id,
            )
            if not nullable_classification:
                builder.add_exact_value(
                    confidence_id,
                    ExactValue(
                        coefficient="5",
                        scale=1,
                        lexical=None,
                        value_kind="number",
                        origin_kind="calculated",
                        unit="confidence.v1",
                    ),
                )
            builder.add_transaction(
                TransactionRecord(
                    transaction_id=transaction_id,
                    observation_id=observation_id,
                    provenance_id=provenance_id,
                    account_id=account_id,
                    amount_value_id=amount_id,
                    date_raw=f"2026-09-{index:02d}",
                    time_raw="12:00:00",
                    datetime_raw=f"2026-09-{index:02d}T12:00:00",
                    type_raw="expense",
                    type_norm="expense",
                    account_text=f"account-{index}",
                    major_raw="Living",
                    minor_raw="Meals",
                    merchant_raw=f"merchant-{index}",
                    category_rule="Food",
                    category_final=None if nullable_classification else "Food",
                    tags_rule_json='["rule"]',
                    tags_ai_json='["ai"]',
                    tags_final_json='["rule","ai"]',
                    confidence_value_id=None if nullable_classification else confidence_id,
                    needs_review=None if nullable_classification else True,
                )
            )
            builder.add_legacy_identifier(
                LegacyIdentifierRecord(
                    entity_id=transaction_id,
                    identifier_kind="row_hash",
                    identifier_value=row_hash,
                    capture_manifest_digest="f" * 64,
                    provenance_id=provenance_id,
                )
            )
            transaction_ids.append(transaction_id)
            amount_ids.append(amount_id)
        builder.finalize()
    _write_activation(authority_paths, generation)
    return authority_paths, _evidence(), generation, transaction_ids, amount_ids


def _facade(
    paths: AuthorityPaths,
    evidence: ActivationEvidence,
    data_dir: Path,
) -> StorageMutationFacade:
    authority = require_repository_authority(paths, evidence)

    class FixedDispatchFacade(StorageMutationFacade):
        def dispatch(self) -> AuthorityDispatch:
            return AuthorityDispatch(paths=paths, authority=authority, evidence=evidence)

    return FixedDispatchFacade(data_dir)


def _request(
    generation: str,
    key: str,
    revision: int,
    *,
    payload: dict[str, Any] | None = None,
    scope: str = "test.ownership",
) -> MutationRequest:
    return MutationRequest(
        command_scope=scope,
        idempotency_key=key,
        payload=payload or {"key": key},
        expected_generation=generation,
        expected_revision=revision,
        actor="test",
        reason="synthetic",
    )


# Explicit fields keep ownership fixtures readable at each behavioral call site.
def _ownership_handler(  # noqa: PLR0913
    *,
    account_id: str,
    party_id: str,
    assertion_id: str,
    value_id: str,
    coefficient: str = "1",
    scale: int = 0,
    completeness: str = "complete",
    supersedes: str | None = None,
) -> Any:
    def handler(context: Any) -> MutationOutcome:
        context.add_exact_value(
            value_id,
            ExactValue(
                coefficient=coefficient,
                scale=scale,
                lexical=None,
                value_kind="rate",
                origin_kind="calculated",
                unit="ownership_share.v1",
            ),
        )
        context.add_ownership_assertion(
            OwnershipAssertionRecord(
                assertion_id=assertion_id,
                account_id=account_id,
                completeness=completeness,
                confirmation_state="confirmed",
                evidence={"kind": "synthetic"},
                unknown_remainder=completeness != "complete",
                confirmed_at=_NOW,
                supersedes_assertion_id=supersedes,
            ),
            [
                OwnershipShareRecord(
                    assertion_id=assertion_id,
                    party_id=party_id,
                    share_value_id=value_id,
                )
            ],
        )
        return MutationOutcome(result={"assertion_id": assertion_id, "coverage_pct": 50.0})

    return handler


def _revision(database: Path) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(
            connection.execute(
                "SELECT dataset_revision FROM repository_meta WHERE singleton = 1"
            ).fetchone()[0]
        )
    finally:
        connection.close()


@pytest.mark.parametrize("source_version", [1, 2, 3])
def test_fresh_and_supported_upgrades_converge_on_v4_without_mutating_sources(
    tmp_path: Path,
    source_version: int,
) -> None:
    latest = schema_module.SQLITE_SCHEMA_VERSION
    ledger = [(version,) for version in range(1, latest + 1)]
    fresh = schema_module.GenerationPaths(tmp_path / "fresh")
    with RepositoryBuilder(fresh, new_entity_id()) as builder:
        builder.finalize()
    with sqlite3.connect(fresh.database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (latest,)
        assert (
            connection.execute(
                "SELECT schema_version FROM schema_migrations ORDER BY schema_version"
            ).fetchall()
            == ledger
        )
        fresh_shape = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()

    source = schema_module.GenerationPaths(tmp_path / f"v{source_version}-source")
    schema_module._prepare_generation_layout(source)
    source_connection = schema_module._connect_builder(source.database)
    generation = new_entity_id()
    try:
        schema_module._apply_schema_v1(source_connection, generation)
        if source_version >= 2:
            schema_module._apply_schema_v2(source_connection)
        if source_version >= 3:
            schema_module._apply_schema_v3(source_connection)
    finally:
        source_connection.close()
    source_before = source.database.read_bytes()
    destination = schema_module.GenerationPaths(tmp_path / f"v{source_version}-upgraded")

    upgraded = upgrade_repository(source.database, destination)

    assert upgraded.schema_version == latest
    assert upgraded.dataset_generation == generation
    assert source.database.read_bytes() == source_before
    with sqlite3.connect(destination.database) as connection:
        assert (
            connection.execute(
                "SELECT schema_version FROM schema_migrations ORDER BY schema_version"
            ).fetchall()
            == ledger
        )
        upgraded_shape = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    assert upgraded_shape == fresh_shape


def test_idempotent_replay_precedes_old_revision_check_and_preserves_result(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    first_request = _request(generation, "first", 0)
    first = service.execute(
        first_request,
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=new_entity_id(),
            value_id=new_entity_id(),
        ),
    )
    service.execute(
        _request(generation, "second", 1),
        _ownership_handler(
            account_id=accounts[1],
            party_id=parties[1],
            assertion_id=new_entity_id(),
            value_id=new_entity_id(),
        ),
    )

    replay = service.execute(first_request, lambda context: pytest.fail("replay called handler"))

    assert replay.replayed is True
    assert replay.changeset_id == first.changeset_id
    assert replay.base_revision == 0
    assert replay.committed_revision == 1
    assert (
        replay.result
        == first.result
        == {"assertion_id": first.result["assertion_id"], "coverage_pct": 50.0}
    )
    assert _revision(paths.generation(generation).database) == 2
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (2,)


def test_idempotency_conflict_and_new_stale_request_write_nothing(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    service.execute(
        _request(generation, "used", 0),
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=new_entity_id(),
            value_id=new_entity_id(),
        ),
    )

    with pytest.raises(MutationConflictError, match="another request"):
        service.execute(
            _request(generation, "used", 0, payload={"different": True}),
            lambda context: pytest.fail("conflict called handler"),
        )
    with pytest.raises(MutationConflictError, match="revision"):
        service.execute(
            _request(generation, "new", 0),
            lambda context: pytest.fail("stale request called handler"),
        )

    assert _revision(paths.generation(generation).database) == 1


def test_request_rejects_float_but_result_allows_finite_float_and_replays(tmp_path: Path) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    with pytest.raises(MutationValidationError, match="Floating-point"):
        service.execute(
            _request(generation, "float-request", 0, payload={"amount": 0.1}),
            lambda context: MutationOutcome(result={}),
        )

    request = _request(generation, "result", 0)
    original = service.execute(
        request,
        lambda context: MutationOutcome(
            result={"coverage_pct": 12.5}, retained_artifacts=("sha256:" + "d" * 64,)
        ),
    )
    replay = service.execute(request, lambda context: pytest.fail("replay called handler"))

    assert original.state_changed is False
    assert replay.result == {"coverage_pct": 12.5}
    assert replay.retained_artifacts == ("sha256:" + "d" * 64,)
    assert _revision(paths.generation(generation).database) == 0


@pytest.mark.parametrize(
    "invalid_outcome",
    [
        MutationOutcome(result=[1]),  # type: ignore[arg-type]
        MutationOutcome(result="ok"),  # type: ignore[arg-type]
        MutationOutcome(result=None),  # type: ignore[arg-type]
        MutationOutcome(result={}, retained_artifacts=(123,)),  # type: ignore[arg-type]
    ],
)
def test_invalid_receipt_envelope_rolls_back_every_domain_write(
    tmp_path: Path,
    invalid_outcome: MutationOutcome,
) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    valid_domain_handler = _ownership_handler(
        account_id=accounts[0],
        party_id=parties[0],
        assertion_id=new_entity_id(),
        value_id=new_entity_id(),
    )

    def invalid_handler(context: Any) -> MutationOutcome:
        valid_domain_handler(context)
        return invalid_outcome

    with pytest.raises(MutationValidationError, match="result|artifact"):
        service.execute(_request(generation, "invalid-receipt", 0), invalid_handler)

    database = paths.generation(generation).database
    assert _revision(database) == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM ownership_assertion_sets").fetchone() == (
            0,
        )
        assert connection.execute("SELECT count(*) FROM exact_values").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM idempotency_requests").fetchone() == (0,)
    assert validate_repository(database).dataset_revision == 0


def test_manual_transaction_edit_is_exact_audited_replayable_and_noop_safe(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, transaction_ids, amount_ids = _active_repository_with_transactions(
        tmp_path
    )
    service = MutationService(paths, evidence)
    database = paths.generation(generation).database

    note_only = service.execute(
        _request(generation, "note", 0, scope="transaction.manual_edit"),
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    note_supplied=True,
                    note="private note",
                )
            )
        ),
    )
    assert note_only.committed_revision == 1
    assert note_only.result["confidence_exact"] == "0.5"

    first_request = _request(generation, "category-a", 1, scope="transaction.manual_edit")
    first = service.execute(
        first_request,
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    add_tags=("manual",),
                    category_supplied=True,
                    category="Travel",
                )
            )
        ),
    )
    service.execute(
        _request(generation, "category-b", 2, scope="transaction.manual_edit"),
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    category_supplied=True,
                    category="Shopping",
                )
            )
        ),
    )

    replay = service.execute(
        first_request,
        lambda context: pytest.fail("manual-edit replay called handler"),
    )
    assert replay.replayed is True
    assert replay.changeset_id == first.changeset_id
    assert replay.result["category_manual"] == "Travel"

    service.execute(
        _request(generation, "category-a-again", 3, scope="transaction.manual_edit"),
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    category_supplied=True,
                    category="Travel",
                )
            )
        ),
    )
    noop = service.execute(
        _request(generation, "same-a", 4, scope="transaction.manual_edit"),
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    add_tags=("manual",),
                    category_supplied=True,
                    category="Travel",
                )
            )
        ),
    )

    assert noop.state_changed is False
    assert noop.committed_revision == 4
    with sqlite3.connect(database) as connection:
        transaction = connection.execute(
            "SELECT amount_value_id, notes_manual, category_manual, category_final, "
            "tags_manual_json, tags_final_json, needs_review FROM transactions "
            "WHERE entity_id = ?",
            (transaction_ids[0],),
        ).fetchone()
        assert transaction == (
            amount_ids[0],
            "private note",
            "Travel",
            "Travel",
            '["manual"]',
            '["rule","ai","manual"]',
            0,
        )
        assert connection.execute(
            "SELECT coefficient, scale FROM exact_values WHERE value_id = ?",
            (amount_ids[0],),
        ).fetchone() == ("1000", 0)
        audit_json = connection.execute(
            "SELECT before_json || after_json FROM changeset_entries "
            "WHERE changeset_id = ? AND entity_kind = 'transaction'",
            (first.changeset_id,),
        ).fetchone()[0]
        assert "amount" not in audit_json
        assert connection.execute(
            "SELECT dataset_revision FROM repository_meta WHERE singleton = 1"
        ).fetchone() == (4,)


def test_manual_transaction_row_hash_must_resolve_to_one_active_mapping(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _ = _active_repository_with_transactions(
        tmp_path,
        row_hashes=("duplicate", "duplicate"),
    )

    with pytest.raises(MutationValidationError, match="multiple transactions"):
        MutationService(paths, evidence).execute(
            _request(generation, "ambiguous", 0, scope="transaction.manual_edit"),
            lambda context: MutationOutcome(
                result=context.edit_manual_transaction(
                    ManualTransactionEdit(
                        identifier="duplicate",
                        add_tags=("manual",),
                    )
                )
            ),
        )

    assert _revision(paths.generation(generation).database) == 0


def test_note_only_edit_preserves_nullable_classification_state(tmp_path: Path) -> None:
    paths, evidence, generation, transaction_ids, _ = _active_repository_with_transactions(
        tmp_path,
        nullable_classification=True,
    )

    receipt = MutationService(paths, evidence).execute(
        _request(generation, "note-only", 0, scope="transaction.manual_edit"),
        lambda context: MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction_ids[0],
                    note_supplied=True,
                    note="note only",
                )
            )
        ),
    )

    assert receipt.state_changed is True
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute(
            "SELECT notes_manual, category_final, confidence_value_id, needs_review, "
            "tags_manual_json, tags_final_json FROM transactions WHERE entity_id = ?",
            (transaction_ids[0],),
        ).fetchone() == (
            "note only",
            None,
            None,
            None,
            "[]",
            '["rule","ai"]',
        )
        entry = connection.execute(
            "SELECT before_json, after_json FROM changeset_entries "
            "WHERE changeset_id = ? AND entity_kind = 'transaction'",
            (receipt.changeset_id,),
        ).fetchone()
        before = json.loads(entry[0])
        after = json.loads(entry[1])
        assert {key for key in before if before[key] != after[key]} == {"notes_manual"}


def _config_mutation(
    paths: AuthorityPaths,
    generation: str,
    content: bytes,
    *,
    config_kind: Literal["rules", "goals"] = "rules",
) -> ConfigRevisionMutation:
    artifact = SourceObjectStore(paths.generation(generation)).publish(io.BytesIO(content))
    occurrence_id = new_entity_id()
    return ConfigRevisionMutation(
        revision=ConfigRevisionRecord(
            revision_id=new_entity_id(),
            config_kind=config_kind,
            artifact_id=artifact.artifact_id,
            occurrence_id=occurrence_id,
            parsed_status="parsed",
            parser_version="synthetic-v1",
            canonical_payload={config_kind: []},
        ),
        occurrence=SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind="config_edit",
            original_filename=f"{config_kind}.yaml",
            imported_at=_NOW,
            parser_version="synthetic-v1",
        ),
        artifact=artifact,
        updated_at=_NOW,
    )


def test_config_revisions_preserve_exact_bytes_noop_and_a_b_a_history(tmp_path: Path) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    rules_a = b"# keep comment\nrules: []\n"
    rules_b = b"# keep comment\nrules:\n  - name: second\n"

    def apply_config(key: str, revision: int, content: bytes) -> Any:
        mutation = _config_mutation(paths, generation, content)
        return service.execute(
            _request(
                generation,
                key,
                revision,
                scope="config.rules.replace",
                payload={"artifact_id": mutation.artifact.artifact_id},
            ),
            lambda context: MutationOutcome(
                result={
                    "artifact_id": mutation.artifact.artifact_id,
                    "changed": context.replace_config(mutation),
                }
            ),
        )

    first = apply_config("a", 0, rules_a)
    noop = apply_config("a-noop", 1, rules_a)
    second = apply_config("b", 1, rules_b)
    third = apply_config("a-again", 2, rules_a)

    assert first.state_changed is True
    assert noop.state_changed is False
    assert noop.committed_revision == 1
    assert second.committed_revision == 2
    assert third.committed_revision == 3
    database = paths.generation(generation).database
    with sqlite3.connect(database) as connection:
        head = connection.execute(
            "SELECT revision.source_artifact_id FROM config_heads AS head "
            "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
            "WHERE head.config_kind = 'rules'"
        ).fetchone()
        assert head == (first.result["artifact_id"],)
        assert connection.execute("SELECT count(*) FROM config_revisions").fetchone() == (3,)
        assert connection.execute(
            "SELECT count(*) FROM source_occurrences WHERE occurrence_kind = 'config_edit'"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT count(*) FROM source_artifacts WHERE source_artifact_id IN (?, ?)",
            (first.result["artifact_id"], second.result["artifact_id"]),
        ).fetchone() == (2,)
    artifact = SourceObjectStore(paths.generation(generation)).verify(str(head[0]))
    assert (paths.generation(generation).root / artifact.relative_path).read_bytes() == rules_a
    assert validate_repository(database).dataset_revision == 3


def test_config_facade_noop_returns_selected_head_and_records_reinterpretation(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    facade = _facade(paths, evidence, tmp_path)
    first_document = ConfigDocument(
        config_kind="rules",
        content=b"rules: []\n",
        parsed_status="parsed",
        canonical_payload={"rules": []},
        parser_version="rules-v1",
    )

    first = facade.replace_config(first_document)
    noop = facade.replace_config(
        first_document,
        identity=MutationIdentity(expected_revision=first.committed_revision),
    )
    reinterpreted = facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=first_document.content,
            parsed_status="parsed",
            canonical_payload={"rules": [{"name": "derived-default"}]},
            parser_version="rules-v2",
        ),
        identity=MutationIdentity(expected_revision=noop.committed_revision),
    )

    assert first.state_changed is True
    assert noop.state_changed is False
    assert noop.result["revision_id"] == first.result["revision_id"]
    assert reinterpreted.state_changed is True
    assert reinterpreted.result["revision_id"] != first.result["revision_id"]
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM config_revisions").fetchone() == (2,)
        assert connection.execute(
            "SELECT revision_id FROM config_heads WHERE config_kind = 'rules'"
        ).fetchone() == (reinterpreted.result["revision_id"],)


def test_config_facade_reads_exact_bytes_from_uri_with_reserved_characters(
    tmp_path: Path,
) -> None:
    unusual_root = tmp_path / "authority#root?query"
    paths, evidence, _, _, _, _ = _active_repository(unusual_root)
    facade = _facade(paths, evidence, unusual_root)
    content = b"goals:\n  monthly_budget:\n    total: 0.10\n"
    document = ConfigDocument.from_validated_yaml(
        "goals",
        content,
        parser_version="goals-v1",
    )

    facade.replace_config(document)

    assert facade.read_config_bytes("goals") == content
    assert document.canonical_payload == {"goals": {"monthly_budget": {"total": "0.10"}}}


def test_config_document_rejects_executable_yaml_tags(tmp_path: Path) -> None:
    marker = tmp_path / "unsafe-loader-marker"
    content = (
        b"rules: !!python/object/apply:os.system\n" + f"  - 'touch {marker.as_posix()}'\n".encode()
    )

    with pytest.raises(ValueError, match="could not be parsed canonically"):
        ConfigDocument.from_validated_yaml(
            "rules",
            content,
            parser_version="rules-v1",
        )

    assert not marker.exists()


def test_config_facade_explicit_replay_survives_later_revision_and_detects_drift(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    facade = _facade(paths, evidence, tmp_path)
    document = ConfigDocument(
        config_kind="goals",
        content=b"goals: []\n",
        parsed_status="parsed",
        canonical_payload={"goals": []},
        parser_version="goals-v1",
    )
    identity = MutationIdentity(
        idempotency_key="stable-goals-edit",
        expected_generation=generation,
        expected_revision=0,
    )

    original = facade.replace_config(document, identity=identity)
    facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=b"rules: []\n",
            parsed_status="parsed",
            canonical_payload={"rules": []},
            parser_version="rules-v1",
        ),
        identity=MutationIdentity(expected_revision=1),
    )
    replay = facade.replace_config(document, identity=identity)

    assert replay.replayed is True
    assert replay.changeset_id == original.changeset_id
    assert replay.committed_revision == 1
    with pytest.raises(MutationConflictError, match="another request"):
        facade.replace_config(
            ConfigDocument(
                config_kind="goals",
                content=document.content,
                parsed_status="parsed",
                canonical_payload={"goals": [{"name": "different"}]},
                parser_version=document.parser_version,
            ),
            identity=identity,
        )
    with pytest.raises(MutationConflictError, match="revision"):
        facade.replace_config(
            document,
            identity=MutationIdentity(expected_revision=0),
        )


def test_config_facade_receipt_failure_rolls_back_but_retains_exact_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    facade = _facade(paths, evidence, tmp_path)
    content = b"# retained\nrules: []\n"

    def fail_receipt(*args: Any, **kwargs: Any) -> None:
        raise OSError("injected receipt failure")

    monkeypatch.setattr(mutation_module, "_store_receipt", fail_receipt)
    with pytest.raises(MutationAbortedError) as captured:
        facade.replace_config(
            ConfigDocument(
                config_kind="rules",
                content=content,
                parsed_status="parsed",
                canonical_payload={"rules": []},
                parser_version="rules-v1",
            )
        )

    assert captured.value.retained_artifacts

    database = paths.generation(generation).database
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM config_heads").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM config_revisions").fetchone() == (0,)
    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    assert SourceObjectStore(paths.generation(generation)).verify(artifact_id).byte_length == len(
        content
    )


@pytest.mark.parametrize("use_uuid", [False, True], ids=["legacy-alias", "uuid"])
def test_active_tag_edit_preview_commit_and_explicit_retry_use_repository(
    tmp_path: Path,
    use_uuid: bool,
) -> None:
    row_hash = "synthetic-row-hash"
    paths, evidence, generation, transaction_ids, _ = _active_repository_with_transactions(
        tmp_path,
        row_hashes=(row_hash,),
    )
    identifier = transaction_ids[0] if use_uuid else row_hash
    facade = _facade(paths, evidence, tmp_path)
    identity = MutationIdentity(
        idempotency_key="stable-manual-edit",
        expected_generation=generation,
        expected_revision=0,
    )

    preview = _compute_tag_edit(
        object(),
        TagEditRequest(identifier, ["manual"], None, "Custom", "private note", True),
        facade=facade,
        identity=identity,
    )
    committed = _compute_tag_edit(
        object(),
        TagEditRequest(identifier, ["manual"], None, "Custom", "private note", False),
        facade=facade,
        identity=identity,
    )
    replay = _compute_tag_edit(
        object(),
        TagEditRequest(identifier, ["manual"], None, "Custom", "private note", False),
        facade=facade,
        identity=identity,
    )

    assert preview["dry_run"] is True
    assert preview["would_update"] is True
    assert preview["transaction"]["tags_manual"] == ["manual"]
    assert committed["updated"] is True
    assert committed["authority"] == "repository"
    assert committed["committed_revision"] == 1
    assert replay["replayed"] is True
    assert replay["changeset_id"] == committed["changeset_id"]
    assert facade.read_manual_transaction(row_hash)["notes_manual"] == "private note"


def test_active_rules_add_update_remove_preserves_exact_config_history(tmp_path: Path) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    facade = _facade(paths, evidence, tmp_path)
    initial = (
        b"# keep rules comment\nversion: 1\nrules:\n"
        b"  - name: coffee_general\n    match: Star\n    fields: [merchant_raw]\n"
        b"    tags: [cafe]\n    priority: 90\n"
        b"  - name: coffee_specific\n    match: Starbucks\n    fields: [merchant_raw]\n"
        b"    tags: [coffee]\n    priority: 80\n"
    )
    seeded = facade.replace_config(
        ConfigDocument.from_validated_yaml("rules", initial, parser_version="finjuice.rules.v1")
    )
    config = Config(data_dir=tmp_path / "unused-data-root")

    added = _compute_add_rule(
        config,
        RuleAddRequest(
            "subscription", "Netflix", "streaming", None, 50, "merchant_raw", False, True
        ),
        facade=facade,
        identity=MutationIdentity(
            idempotency_key="rules-add",
            expected_generation=generation,
            expected_revision=seeded.committed_revision,
        ),
    )
    added_replay = _compute_add_rule(
        config,
        RuleAddRequest(
            "subscription", "Netflix", "streaming", None, 50, "merchant_raw", False, True
        ),
        facade=facade,
        identity=MutationIdentity(
            idempotency_key="rules-add",
            expected_generation=generation,
            expected_revision=seeded.committed_revision,
        ),
    )
    updated = _compute_add_rule(
        config,
        RuleAddRequest(
            "subscription",
            "Netflix|Disney",
            "streaming,media",
            "Entertainment",
            60,
            "merchant_raw",
            False,
            True,
        ),
        facade=facade,
        identity=MutationIdentity(expected_revision=2),
    )
    remove_identity = MutationIdentity(
        idempotency_key="rules-remove",
        expected_generation=generation,
        expected_revision=3,
    )
    removed = _compute_remove_rule(
        config,
        name="subscription",
        json_output=True,
        facade=facade,
        identity=remove_identity,
    )
    removed_replay = _compute_remove_rule(
        config,
        name="subscription",
        json_output=True,
        facade=facade,
        identity=remove_identity,
    )

    assert added["action"] == "added"
    assert added["committed_revision"] == 2
    assert added_replay["action"] == "added"
    assert added_replay["replayed"] is True
    assert updated["action"] == "updated"
    assert updated["committed_revision"] == 3
    assert removed["committed_revision"] == 4
    assert removed_replay["replayed"] is True
    assert removed_replay["action"] == "removed"
    assert facade.read_config_bytes("rules") == initial
    schema_dir = Path(__file__).resolve().parents[2] / "schemas"
    for payload, schema_name in (
        (added, "rules_add"),
        (added_replay, "rules_add"),
        (updated, "rules_add"),
        (removed, "rules_remove"),
        (removed_replay, "rules_remove"),
    ):
        schema = json.loads((schema_dir / f"{schema_name}.schema.json").read_text())
        jsonschema.validate(payload["validation"], schema["properties"]["validation"])
        assert payload["validation"]["total_problems"] > 0
        assert payload["validation"]["problems"] == []
    assert added_replay["validation"] == added["validation"]
    assert removed_replay["validation"] == removed["validation"]
    late_replay = _compute_add_rule(
        config,
        RuleAddRequest(
            "subscription", "Netflix", "streaming", None, 50, "merchant_raw", False, True
        ),
        facade=facade,
        identity=MutationIdentity(
            idempotency_key="rules-add",
            expected_generation=generation,
            expected_revision=seeded.committed_revision,
        ),
    )
    assert late_replay["replayed"] is True
    assert late_replay["validation"] == added["validation"]
    assert late_replay["rule"] == added["rule"]
    assert facade.read_config_bytes("rules") == initial


def test_authoritative_rule_bytes_preserve_numeric_condition_lexemes() -> None:
    rules = load_rules_bytes(
        b"version: 1\nrules:\n"
        b"  - name: exact_threshold\n"
        b"    conditions:\n"
        b"      - field: amount\n"
        b"        op: greater_than\n"
        b"        value: 1.234567890123456789e-400\n"
        b"    tags: [exact]\n"
        b"    confidence: 0.75\n"
    )

    assert rules[0].conditions[0].value == "1.234567890123456789e-400"
    assert rules[0].confidence == 0.75


def test_active_budget_edit_is_exact_atomic_and_replayable(tmp_path: Path) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    facade = _facade(paths, evidence, tmp_path)
    initial = (
        b"# keep goals comment\n"
        b"meta:\n  tiny: 1.234567890123456789e-400\n"
        b"version: 1\nmonthly_budget:\n  total: 1000\n  categories: {}\n"
    )
    seeded = facade.replace_config(
        ConfigDocument.from_validated_yaml("goals", initial, parser_version="finjuice.goals.v1")
    )
    config = Config(data_dir=tmp_path / "unused-data-root")
    identity = MutationIdentity(
        idempotency_key="budget-edit",
        expected_generation=generation,
        expected_revision=seeded.committed_revision,
    )

    receipt = facade.mutate_config(
        ConfigMutation(
            "goals",
            {"action": "budget_edit", "updates": ["total=2500"]},
            _budget_edit_transform(config, ["total=2500"]),
        ),
        identity=identity,
    )
    replay = facade.mutate_config(
        ConfigMutation(
            "goals",
            {"action": "budget_edit", "updates": ["total=2500"]},
            _budget_edit_transform(config, ["total=2500"]),
        ),
        identity=identity,
    )

    content = facade.read_config_bytes("goals")
    assert content is not None
    assert b"# keep goals comment" in content
    assert b"1.234567890123456789e-400" in content
    assert b"total: 2500" in content
    assert receipt.committed_revision == 2
    assert replay.replayed is True
    assert replay.changeset_id == receipt.changeset_id


def test_config_fault_rolls_back_head_revision_and_audit_but_retains_object(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, _ = _active_repository(tmp_path)
    mutation = _config_mutation(paths, generation, b"rules: []\n")

    def fail_after_config(context: Any) -> MutationOutcome:
        context.replace_config(mutation)
        raise OSError("injected after config mutation")

    with pytest.raises(MutationAbortedError) as captured:
        MutationService(paths, evidence).execute(
            _request(generation, "config-fault", 0, scope="config.rules.replace"),
            fail_after_config,
        )

    assert captured.value.retained_artifacts == (mutation.artifact.artifact_id,)
    database = paths.generation(generation).database
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM config_heads").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM config_revisions").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM idempotency_requests").fetchone() == (0,)
    assert validate_repository(database).dataset_revision == 0


@pytest.mark.parametrize("fault_target", ["_insert_audit_event", "_store_receipt"])
def test_audit_and_receipt_faults_roll_back_domain_revision_and_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_target: str,
) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    assertion_id = new_entity_id()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError(f"injected {fault_target}")

    monkeypatch.setattr(mutation_module, fault_target, fail)
    with pytest.raises(OSError, match="injected"):
        service.execute(
            _request(generation, fault_target, 0),
            _ownership_handler(
                account_id=accounts[0],
                party_id=parties[0],
                assertion_id=assertion_id,
                value_id=new_entity_id(),
            ),
        )

    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM idempotency_requests").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM ownership_assertion_sets WHERE assertion_id = ?",
            (assertion_id,),
        ).fetchone() == (0,)
    assert _revision(paths.generation(generation).database) == 0


def test_exact_ownership_partial_overlap_and_explicit_supersession(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    scale = 120
    coefficient = "1" + "0" * 119
    first_assertion = new_entity_id()
    service.execute(
        _request(generation, "partial", 0),
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=first_assertion,
            value_id=new_entity_id(),
            coefficient=coefficient,
            scale=scale,
            completeness="partial",
        ),
    )

    with pytest.raises(RepositoryIntegrityError, match="overlap"):
        service.execute(
            _request(generation, "overlap", 1),
            _ownership_handler(
                account_id=accounts[0],
                party_id=parties[1],
                assertion_id=new_entity_id(),
                value_id=new_entity_id(),
            ),
        )

    corrected = new_entity_id()
    receipt = service.execute(
        _request(generation, "correction", 1),
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[1],
            assertion_id=corrected,
            value_id=new_entity_id(),
            supersedes=first_assertion,
        ),
    )

    assert receipt.committed_revision == 2
    assert validate_repository(paths.generation(generation).database).dataset_revision == 2
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM ownership_assertion_sets").fetchone() == (
            2,
        )


def test_complete_ownership_uses_exact_integer_arithmetic_for_long_shares(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    assertion_id = new_entity_id()
    scale = 120
    value_ids = [new_entity_id(), new_entity_id()]

    def exact_complete(context: Any) -> MutationOutcome:
        for value_id, coefficient in zip(
            value_ids,
            ("1" + "0" * 119, "9" + "0" * 119),
            strict=True,
        ):
            context.add_exact_value(
                value_id,
                ExactValue(
                    coefficient=coefficient,
                    scale=scale,
                    lexical=None,
                    value_kind="rate",
                    origin_kind="calculated",
                    unit="ownership_share.v1",
                ),
            )
        context.add_ownership_assertion(
            OwnershipAssertionRecord(
                assertion_id=assertion_id,
                account_id=accounts[0],
                completeness="complete",
                confirmation_state="confirmed",
                evidence={"precision": scale},
                unknown_remainder=False,
                confirmed_at=_NOW,
            ),
            [
                OwnershipShareRecord(assertion_id, parties[0], value_ids[0]),
                OwnershipShareRecord(assertion_id, parties[1], value_ids[1]),
            ],
        )
        return MutationOutcome(result={})

    receipt = service.execute(_request(generation, "exact-complete", 0), exact_complete)

    assert receipt.committed_revision == 1
    assert validate_repository(paths.generation(generation).database).dataset_revision == 1


def test_ownership_share_wrong_semantic_unit_rolls_back_entire_mutation(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    value_id = new_entity_id()

    def wrong_unit(context: Any) -> MutationOutcome:
        context.add_exact_value(
            value_id,
            ExactValue(
                coefficient="1",
                scale=0,
                lexical=None,
                value_kind="rate",
                origin_kind="calculated",
                unit="fx_rate.v1",
            ),
        )
        assertion_id = new_entity_id()
        context.add_ownership_assertion(
            OwnershipAssertionRecord(
                assertion_id=assertion_id,
                account_id=accounts[0],
                completeness="complete",
                confirmation_state="confirmed",
                evidence={"kind": "wrong-unit"},
                unknown_remainder=False,
                confirmed_at=_NOW,
            ),
            [OwnershipShareRecord(assertion_id, parties[0], value_id)],
        )
        return MutationOutcome(result={})

    with pytest.raises(MutationValidationError, match="ownership_share.v1"):
        service.execute(_request(generation, "wrong-unit", 0), wrong_unit)

    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM exact_values WHERE value_id = ?", (value_id,)
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM ownership_assertion_sets").fetchone() == (
            0,
        )
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM idempotency_requests").fetchone() == (0,)
    assert _revision(paths.generation(generation).database) == 0


def test_repository_validation_rejects_wrong_ownership_share_semantic_unit(
    tmp_path: Path,
) -> None:
    paths, _, generation, parties, accounts, _ = _active_repository(tmp_path)
    database = paths.generation(generation).database
    value_id = new_entity_id()
    assertion_id = new_entity_id()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO exact_values "
            "(value_id, value_kind, coefficient, scale, lexical, origin_kind) "
            "VALUES (?, 'rate', '1', 0, NULL, 'calculated')",
            (value_id,),
        )
        connection.execute(
            "INSERT INTO rate_values (value_id, unit) VALUES (?, 'fx_rate.v1')",
            (value_id,),
        )
        connection.execute(
            "INSERT INTO ownership_assertion_sets "
            "(assertion_id, account_id, completeness, unknown_remainder, confirmation_state, "
            "evidence_json, confirmed_at) VALUES (?, ?, 'complete', 0, 'confirmed', '{}', ?)",
            (assertion_id, accounts[0], _NOW),
        )
        connection.execute(
            "INSERT INTO ownership_assertion_shares "
            "(assertion_id, party_id, share_value_id) VALUES (?, ?, ?)",
            (assertion_id, parties[0], value_id),
        )

    with pytest.raises(RepositoryIntegrityError, match="ownership_share.v1"):
        validate_repository(database)


def test_relation_correction_must_keep_same_ordered_entity_pair(tmp_path: Path) -> None:
    paths, evidence, generation, _, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    original_id = new_entity_id()

    service.execute(
        _request(generation, "relation", 0, scope="test.relation"),
        lambda context: (
            context.add_relation_assertion(
                EntityRelationAssertionRecord(
                    assertion_id=original_id,
                    subject_entity_id=accounts[0],
                    object_entity_id=accounts[1],
                    relation_kind="overlaps",
                    confirmation_state="confirmed",
                    evidence={"kind": "synthetic"},
                    confirmed_at=_NOW,
                )
            )
            or MutationOutcome(result={})
        ),
    )

    with pytest.raises(RepositoryIntegrityError, match="ordered entity pair"):
        service.execute(
            _request(generation, "bad-correction", 1, scope="test.relation"),
            lambda context: (
                context.add_relation_assertion(
                    EntityRelationAssertionRecord(
                        assertion_id=new_entity_id(),
                        subject_entity_id=accounts[0],
                        object_entity_id=accounts[2],
                        relation_kind="excludes",
                        confirmation_state="confirmed",
                        evidence={"kind": "correction"},
                        confirmed_at=_NOW,
                        supersedes_assertion_id=original_id,
                    )
                )
                or MutationOutcome(result={})
            ),
        )
    assert _revision(paths.generation(generation).database) == 1


def test_contradictory_active_confirmed_relations_require_explicit_supersession(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)
    includes_id = new_entity_id()

    def relation(
        assertion_id: str,
        kind: Literal["includes", "overlaps", "excludes", "unknown"],
        confirmation_state: Literal["unconfirmed", "confirmed", "rejected"],
        *,
        supersedes: str | None = None,
    ) -> Any:
        return lambda context: (
            context.add_relation_assertion(
                EntityRelationAssertionRecord(
                    assertion_id=assertion_id,
                    subject_entity_id=accounts[0],
                    object_entity_id=accounts[1],
                    relation_kind=kind,
                    confirmation_state=confirmation_state,
                    evidence={"kind": kind},
                    effective_from="2026-01-01",
                    effective_to="2026-12-31",
                    confirmed_at=_NOW if confirmation_state == "confirmed" else None,
                    supersedes_assertion_id=supersedes,
                )
            )
            or MutationOutcome(result={})
        )

    service.execute(
        _request(generation, "includes", 0, scope="test.relation"),
        relation(includes_id, "includes", "confirmed"),
    )
    service.execute(
        _request(generation, "unknown", 1, scope="test.relation"),
        relation(new_entity_id(), "unknown", "confirmed"),
    )
    service.execute(
        _request(generation, "unconfirmed-excludes", 2, scope="test.relation"),
        relation(new_entity_id(), "excludes", "unconfirmed"),
    )

    with pytest.raises(RepositoryIntegrityError, match="contradict"):
        service.execute(
            _request(generation, "conflicting-excludes", 3, scope="test.relation"),
            relation(new_entity_id(), "excludes", "confirmed"),
        )
    assert _revision(paths.generation(generation).database) == 3

    receipt = service.execute(
        _request(generation, "corrected-excludes", 3, scope="test.relation"),
        relation(new_entity_id(), "excludes", "confirmed", supersedes=includes_id),
    )
    assert receipt.committed_revision == 4


@pytest.mark.parametrize(
    ("effective_from", "effective_to"),
    [
        ("2026-2-03", None),
        ("2026-02-30", None),
        ("2026-01-01T00:00:00Z", None),
        ("2026-12-31", "2026-01-01"),
    ],
)
def test_relation_effective_bounds_require_canonical_ordered_calendar_dates(
    tmp_path: Path,
    effective_from: str,
    effective_to: str | None,
) -> None:
    paths, evidence, generation, _, accounts, _ = _active_repository(tmp_path)
    service = MutationService(paths, evidence)

    def invalid_interval(context: Any) -> MutationOutcome:
        context.add_relation_assertion(
            EntityRelationAssertionRecord(
                assertion_id=new_entity_id(),
                subject_entity_id=accounts[0],
                object_entity_id=accounts[1],
                relation_kind="includes",
                confirmation_state="unconfirmed",
                evidence={},
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
        return MutationOutcome(result={})

    with pytest.raises(MutationValidationError, match="Effective"):
        service.execute(_request(generation, "invalid-date", 0), invalid_interval)
    assert _revision(paths.generation(generation).database) == 0


# This helper mirrors the complete persisted intake lineage in one fixture operation.
def _add_intake_proposal(  # noqa: PLR0913
    context: Any,
    *,
    artifact_id: str,
    generation: str,
    proposal_id: str,
    occurrence_id: str,
    extraction_id: str,
    key: str,
    expected_revision: int,
    payload: dict[str, Any],
    extraction_payload: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> None:
    intake_artifact_id = new_entity_id()
    context.add_intake_artifact(
        AgentIntakeArtifactRecord(
            intake_artifact_id=intake_artifact_id,
            source_artifact_id=artifact_id,
            media_type="application/json",
            evidence={"source": "synthetic"},
            created_at=_NOW,
        )
    )
    context.add_intake_occurrence(
        AgentIntakeOccurrenceRecord(
            occurrence_id=occurrence_id,
            intake_artifact_id=intake_artifact_id,
            channel="test",
            received_at=_NOW,
            detail={"sequence": 1},
        )
    )
    context.add_intake_extraction(
        AgentIntakeExtractionRecord(
            extraction_id=extraction_id,
            occurrence_id=occurrence_id,
            extractor="test-v1",
            payload=payload if extraction_payload is None else extraction_payload,
            created_at=_NOW,
        )
    )
    context.add_intake_proposal(
        AgentIntakeProposalRecord(
            proposal_id=proposal_id,
            extraction_id=extraction_id,
            policy_version="policy-v1",
            command_scope="agent.apply",
            idempotency_key=key,
            expected_generation=generation,
            expected_revision=expected_revision,
            payload=payload,
            created_at=_NOW,
        )
    )


def test_intake_allows_list_extraction_with_mapping_proposal_and_confirmed_application(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    service = MutationService(paths, evidence)
    proposal_id = new_entity_id()
    occurrence_id = new_entity_id()
    extraction_id = new_entity_id()
    proposal_payload = {"action": "tag", "entity_id": new_entity_id()}

    service.execute(
        _request(generation, "capture", 0, scope="agent.capture"),
        lambda context: (
            _add_intake_proposal(
                context,
                artifact_id=artifact_id,
                generation=generation,
                proposal_id=proposal_id,
                occurrence_id=occurrence_id,
                extraction_id=extraction_id,
                key="apply",
                expected_revision=1,
                payload=proposal_payload,
                extraction_payload=[{"candidate": "tag"}],
            )
            or MutationOutcome(result={"proposal_id": proposal_id})
        ),
    )

    confirmation_id = new_entity_id()

    def apply(context: Any) -> MutationOutcome:
        context.add_intake_confirmation(
            AgentIntakeConfirmationRecord(
                confirmation_id=confirmation_id,
                proposal_id=proposal_id,
                confirmation_state="confirmed",
                actor="test",
                detail={"approved": True},
                confirmed_at=_NOW,
            )
        )
        context.add_intake_application(
            AgentIntakeApplicationRecord(
                proposal_id=proposal_id,
                confirmation_id=confirmation_id,
                changeset_id=context.changeset_id,
                applied_at=_NOW,
            )
        )
        return MutationOutcome(result={"applied": True})

    receipt = service.execute(
        _request(generation, "apply", 1, scope="agent.apply", payload=proposal_payload),
        apply,
    )

    assert receipt.committed_revision == 2
    assert validate_repository(paths.generation(generation).database).dataset_revision == 2


def test_intake_rejects_list_proposal_and_rolls_back_its_lineage(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    service = MutationService(paths, evidence)
    extraction_payload = [{"candidate": "tag"}]

    def add_list_proposal(context: Any) -> MutationOutcome:
        intake_artifact_id = new_entity_id()
        occurrence_id = new_entity_id()
        extraction_id = new_entity_id()
        context.add_intake_artifact(
            AgentIntakeArtifactRecord(
                intake_artifact_id=intake_artifact_id,
                source_artifact_id=artifact_id,
                media_type="application/json",
                evidence={"source": "synthetic"},
                created_at=_NOW,
            )
        )
        context.add_intake_occurrence(
            AgentIntakeOccurrenceRecord(
                occurrence_id=occurrence_id,
                intake_artifact_id=intake_artifact_id,
                channel="test",
                received_at=_NOW,
                detail={"sequence": 1},
            )
        )
        context.add_intake_extraction(
            AgentIntakeExtractionRecord(
                extraction_id=extraction_id,
                occurrence_id=occurrence_id,
                extractor="test-v1",
                payload=extraction_payload,
                created_at=_NOW,
            )
        )
        context.add_intake_proposal(
            AgentIntakeProposalRecord(
                proposal_id=new_entity_id(),
                extraction_id=extraction_id,
                policy_version="policy-v1",
                command_scope="agent.apply",
                idempotency_key="apply-list",
                expected_generation=generation,
                expected_revision=1,
                payload=extraction_payload,  # type: ignore[arg-type]
                created_at=_NOW,
            )
        )
        return MutationOutcome(result={})

    with pytest.raises(MutationValidationError, match="proposal payload"):
        service.execute(
            _request(generation, "list-proposal", 0, scope="agent.capture"),
            add_list_proposal,
        )

    database = paths.generation(generation).database
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM agent_intake_extractions").fetchone() == (
            0,
        )
        assert connection.execute("SELECT count(*) FROM agent_intake_proposals").fetchone() == (0,)
    assert validate_repository(database).dataset_revision == 0


@pytest.mark.parametrize("failure", ["rejected", "wrong_proposal", "payload", "stale"])
def test_invalid_intake_application_rolls_back(
    tmp_path: Path,
    failure: str,
) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    service = MutationService(paths, evidence)
    proposal_id = new_entity_id()
    payload = {"action": "tag"}
    expected_revision = 99 if failure == "stale" else 1
    service.execute(
        _request(generation, "capture", 0, scope="agent.capture"),
        lambda context: (
            _add_intake_proposal(
                context,
                artifact_id=artifact_id,
                generation=generation,
                proposal_id=proposal_id,
                occurrence_id=new_entity_id(),
                extraction_id=new_entity_id(),
                key="apply",
                expected_revision=expected_revision,
                payload=payload,
            )
            or MutationOutcome(result={})
        ),
    )
    confirmation_id = new_entity_id()
    confirmation_proposal = new_entity_id() if failure == "wrong_proposal" else proposal_id

    def invalid_apply(context: Any) -> MutationOutcome:
        context.add_intake_confirmation(
            AgentIntakeConfirmationRecord(
                confirmation_id=confirmation_id,
                proposal_id=confirmation_proposal,
                confirmation_state="rejected" if failure == "rejected" else "confirmed",
                actor="test",
                detail={},
                confirmed_at=_NOW,
            )
        )
        context.add_intake_application(
            AgentIntakeApplicationRecord(
                proposal_id=proposal_id,
                confirmation_id=confirmation_id,
                changeset_id=context.changeset_id,
                applied_at=_NOW,
            )
        )
        return MutationOutcome(result={})

    apply_payload = {"action": "other"} if failure == "payload" else payload
    with pytest.raises((RepositoryIntegrityError, sqlite3.IntegrityError)):
        service.execute(
            _request(generation, "apply", 1, scope="agent.apply", payload=apply_payload),
            invalid_apply,
        )

    assert _revision(paths.generation(generation).database) == 1
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM agent_intake_applications").fetchone() == (
            0,
        )


def test_stale_intake_can_be_reproposed_at_current_revision_and_applied(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    service = MutationService(paths, evidence)
    extraction_id = new_entity_id()
    stale_proposal_id = new_entity_id()
    payload = {"action": "tag", "entity_id": new_entity_id()}
    service.execute(
        _request(generation, "capture", 0, scope="agent.capture"),
        lambda context: (
            _add_intake_proposal(
                context,
                artifact_id=artifact_id,
                generation=generation,
                proposal_id=stale_proposal_id,
                occurrence_id=new_entity_id(),
                extraction_id=extraction_id,
                key="apply-stale",
                expected_revision=1,
                payload=payload,
            )
            or MutationOutcome(result={})
        ),
    )

    unrelated_value_id = new_entity_id()
    service.execute(
        _request(generation, "unrelated", 1, scope="test.unrelated"),
        lambda context: (
            context.add_exact_value(
                unrelated_value_id,
                ExactValue(
                    coefficient="1",
                    scale=0,
                    lexical=None,
                    value_kind="number",
                    origin_kind="calculated",
                    unit="count.v1",
                ),
            )
            or MutationOutcome(result={})
        ),
    )

    def apply(proposal_id: str, confirmation_id: str) -> Any:
        return lambda context: (
            context.add_intake_confirmation(
                AgentIntakeConfirmationRecord(
                    confirmation_id=confirmation_id,
                    proposal_id=proposal_id,
                    confirmation_state="confirmed",
                    actor="test",
                    detail={"approved": True},
                    confirmed_at=_NOW,
                )
            )
            or context.add_intake_application(
                AgentIntakeApplicationRecord(
                    proposal_id=proposal_id,
                    confirmation_id=confirmation_id,
                    changeset_id=context.changeset_id,
                    applied_at=_NOW,
                )
            )
            or MutationOutcome(result={"applied": proposal_id})
        )

    with pytest.raises(RepositoryIntegrityError, match="matching confirmed request"):
        service.execute(
            _request(generation, "apply-stale", 2, scope="agent.apply", payload=payload),
            apply(stale_proposal_id, new_entity_id()),
        )
    assert _revision(paths.generation(generation).database) == 2

    current_proposal_id = new_entity_id()
    service.execute(
        _request(generation, "repropose", 2, scope="agent.capture"),
        lambda context: (
            context.add_intake_proposal(
                AgentIntakeProposalRecord(
                    proposal_id=current_proposal_id,
                    extraction_id=extraction_id,
                    policy_version="policy-v1",
                    command_scope="agent.apply",
                    idempotency_key="apply-current",
                    expected_generation=generation,
                    expected_revision=3,
                    payload=payload,
                    created_at=_NOW,
                )
            )
            or MutationOutcome(result={})
        ),
    )
    receipt = service.execute(
        _request(generation, "apply-current", 3, scope="agent.apply", payload=payload),
        apply(current_proposal_id, new_entity_id()),
    )

    assert receipt.committed_revision == 4
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM agent_intake_proposals").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM agent_intake_applications").fetchone() == (
            1,
        )


def test_same_evidence_reuses_artifact_but_distinct_occurrences_remain_possible(
    tmp_path: Path,
) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    repository_paths = paths.generation(generation)
    verified = SourceObjectStore(repository_paths).verify(artifact_id)
    service = MutationService(paths, evidence)
    intake_artifact_id = new_entity_id()
    occurrence_ids = [new_entity_id(), new_entity_id()]

    def receive_twice(context: Any) -> MutationOutcome:
        context.register_source_artifact(verified)
        context.add_intake_artifact(
            AgentIntakeArtifactRecord(
                intake_artifact_id=intake_artifact_id,
                source_artifact_id=artifact_id,
                media_type="application/octet-stream",
                evidence={},
                created_at=_NOW,
            )
        )
        for occurrence_id in occurrence_ids:
            context.add_intake_occurrence(
                AgentIntakeOccurrenceRecord(
                    occurrence_id=occurrence_id,
                    intake_artifact_id=intake_artifact_id,
                    channel="test",
                    received_at=_NOW,
                    detail={"occurrence": occurrence_id},
                )
            )
        return MutationOutcome(result={})

    service.execute(_request(generation, "receive", 0, scope="agent.capture"), receive_twice)

    with sqlite3.connect(repository_paths.database) as connection:
        assert connection.execute("SELECT count(*) FROM agent_intake_artifacts").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM agent_intake_occurrences").fetchone() == (
            2,
        )

    def duplicate_artifact(context: Any) -> MutationOutcome:
        context.add_intake_artifact(
            AgentIntakeArtifactRecord(
                intake_artifact_id=new_entity_id(),
                source_artifact_id=artifact_id,
                media_type="application/octet-stream",
                evidence={},
                created_at=_NOW,
            )
        )
        return MutationOutcome(result={})

    with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
        service.execute(
            _request(generation, "duplicate", 1, scope="agent.capture"),
            duplicate_artifact,
        )
    assert _revision(repository_paths.database) == 1


def test_intake_lineage_deduplicates_extraction_and_proposal_by_policy(tmp_path: Path) -> None:
    paths, evidence, generation, _, _, artifact_id = _active_repository(
        tmp_path,
        with_artifact=True,
    )
    assert artifact_id is not None
    service = MutationService(paths, evidence)
    occurrence_id = new_entity_id()
    extraction_id = new_entity_id()
    proposal_id = new_entity_id()
    payload = {"fact": "same evidence"}
    _ = service.execute(
        _request(generation, "capture", 0, scope="agent.capture"),
        lambda context: (
            _add_intake_proposal(
                context,
                artifact_id=artifact_id,
                generation=generation,
                proposal_id=proposal_id,
                occurrence_id=occurrence_id,
                extraction_id=extraction_id,
                key="future-apply",
                expected_revision=1,
                payload=payload,
            )
            or MutationOutcome(result={})
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
        service.execute(
            _request(generation, "duplicate-extraction", 1, scope="agent.capture"),
            lambda context: (
                context.add_intake_extraction(
                    AgentIntakeExtractionRecord(
                        extraction_id=new_entity_id(),
                        occurrence_id=occurrence_id,
                        extractor="test-v1",
                        payload=payload,
                        created_at=_NOW,
                    )
                )
                or MutationOutcome(result={})
            ),
        )

    service.execute(
        _request(generation, "new-extractor", 1, scope="agent.capture"),
        lambda context: (
            context.add_intake_extraction(
                AgentIntakeExtractionRecord(
                    extraction_id=new_entity_id(),
                    occurrence_id=occurrence_id,
                    extractor="test-v2",
                    payload=payload,
                    created_at=_NOW,
                )
            )
            or MutationOutcome(result={})
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
        service.execute(
            _request(generation, "duplicate-proposal", 2, scope="agent.capture"),
            lambda context: (
                context.add_intake_proposal(
                    AgentIntakeProposalRecord(
                        proposal_id=new_entity_id(),
                        extraction_id=extraction_id,
                        policy_version="policy-v1",
                        command_scope="agent.apply",
                        idempotency_key="another-apply-key",
                        expected_generation=generation,
                        expected_revision=1,
                        payload=payload,
                        created_at=_NOW,
                    )
                )
                or MutationOutcome(result={})
            ),
        )
    assert _revision(paths.generation(generation).database) == 2


def test_authority_absence_candidate_inert_and_present_invalid_fails_closed(tmp_path: Path) -> None:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    evidence = _evidence()
    candidate = paths.generation(new_entity_id())
    with RepositoryBuilder(candidate, candidate.root.name) as builder:
        builder.finalize()

    assert isinstance(resolve_authority(paths, evidence), LegacyAuthority)
    with shared_write_lease(paths):
        assert require_legacy_authority(paths, evidence).kind == "legacy"

    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    paths.activation.write_text("{broken", encoding="utf-8")
    with shared_write_lease(paths):
        with pytest.raises(AuthorityIntegrityError, match="valid JSON"):
            require_legacy_authority(paths, evidence)
    assert sentinel.read_bytes() == b"unchanged"


def test_authority_uses_external_identity_and_fixed_activation_baseline(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    mismatched = ActivationEvidence(
        installed_release_version=evidence.installed_release_version,
        installed_release_artifact_sha256="d" * 64,
        verified_migration_manifest_sha256=evidence.verified_migration_manifest_sha256,
        verified_pre_cutover_backup_manifest_sha256=(
            evidence.verified_pre_cutover_backup_manifest_sha256
        ),
    )
    with pytest.raises(AuthorityIntegrityError, match="installed release"):
        resolve_authority(paths, mismatched)

    service = MutationService(paths, evidence)
    service.execute(
        _request(generation, "advance", 0),
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=new_entity_id(),
            value_id=new_entity_id(),
        ),
    )
    resolved = resolve_authority(paths, evidence)

    assert isinstance(resolved, RepositoryAuthority)
    assert resolved.activation.dataset_revision == 0
    assert inspect_repository(resolved.paths.database).dataset_revision == 1


def _hold_exclusive_lease(
    control_root: str,
    generations_root: str,
    ready: Any,
    release: Any,
) -> None:
    paths = AuthorityPaths(Path(control_root), Path(generations_root))
    with exclusive_maintenance_lease(paths):
        ready.set()
        release.wait(10)


def test_coordination_lease_has_bounded_contention(tmp_path: Path) -> None:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_exclusive_lease,
        args=(str(paths.control_root), str(paths.generations_root), ready, release),
    )
    process.start()
    assert ready.wait(10)
    try:
        with pytest.raises(AuthorityConflictError, match="timed out"):
            with shared_write_lease(paths, timeout_ms=20):
                pytest.fail("contended lease was acquired")
    finally:
        release.set()
        process.join(10)
    assert process.exitcode == 0


def test_coordination_lease_fails_explicitly_on_unsupported_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    monkeypatch.setattr(authority_module, "_fcntl", None)
    monkeypatch.setattr(authority_module, "_msvcrt", None)

    with pytest.raises(AuthorityIntegrityError, match="unsupported"):
        with shared_write_lease(paths):
            pytest.fail("unsupported lease was acquired")


def test_windows_lease_backend_is_bounded_and_same_thread_reentrant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        def locking(self, descriptor: int, mode: int, byte_count: int) -> None:
            del descriptor
            self.calls.append((mode, byte_count))

    backend = FakeMsvcrt()
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    monkeypatch.setattr(authority_module, "_fcntl", None)
    monkeypatch.setattr(authority_module, "_msvcrt", backend)

    outer = shared_write_lease(paths)
    with outer:
        with pytest.raises(AuthorityConflictError, match="already entered"):
            outer.__enter__()
        with shared_write_lease(paths):
            pass
        with pytest.raises(AuthorityConflictError, match="cannot be upgraded"):
            with exclusive_maintenance_lease(paths, timeout_ms=0):
                pytest.fail("nested shared lease was upgraded")

    assert backend.calls == [(backend.LK_NBLCK, 1), (backend.LK_UNLCK, 1)]


def test_coordination_lease_releases_local_lock_after_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    original_prepare = authority_module._prepare_coordination_root
    attempts = 0

    def interrupt_once(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KeyboardInterrupt
        original_prepare(path)

    monkeypatch.setattr(authority_module, "_prepare_coordination_root", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        with shared_write_lease(paths):
            pytest.fail("interrupted lease was acquired")

    errors: list[BaseException] = []

    def acquire_from_another_thread() -> None:
        try:
            with shared_write_lease(paths, timeout_ms=100):
                pass
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=acquire_from_another_thread)
    thread.start()
    thread.join(1)

    assert not thread.is_alive()
    assert errors == []


# Multiprocessing targets use primitive arguments so spawn can serialize them reliably.
def _interrupted_writer(  # noqa: PLR0913
    control_root: str,
    generations_root: str,
    generation: str,
    account_id: str,
    party_id: str,
    assertion_id: str,
    value_id: str,
    inserted: Any,
) -> None:
    paths = AuthorityPaths(Path(control_root), Path(generations_root))
    service = MutationService(paths, _evidence())

    def pause_after_domain_write(context: Any) -> MutationOutcome:
        result = _ownership_handler(
            account_id=account_id,
            party_id=party_id,
            assertion_id=assertion_id,
            value_id=value_id,
        )(context)
        inserted.set()
        multiprocessing.Event().wait(60)
        return result

    service.execute(_request(generation, "interrupted", 0), pause_after_domain_write)


def test_process_termination_rolls_back_and_same_request_can_apply_once(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    assertion_id = new_entity_id()
    value_id = new_entity_id()
    context = multiprocessing.get_context("spawn")
    inserted = context.Event()
    process = context.Process(
        target=_interrupted_writer,
        args=(
            str(paths.control_root),
            str(paths.generations_root),
            generation,
            accounts[0],
            parties[0],
            assertion_id,
            value_id,
            inserted,
        ),
    )
    process.start()
    assert inserted.wait(10)
    process.terminate()
    process.join(10)
    assert process.exitcode is not None and process.exitcode != 0
    assert _revision(paths.generation(generation).database) == 0

    receipt = MutationService(paths, evidence).execute(
        _request(generation, "interrupted", 0),
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=assertion_id,
            value_id=value_id,
        ),
    )

    assert receipt.committed_revision == 1
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (1,)


def test_rollback_reports_immutable_object_that_remains_published(tmp_path: Path) -> None:
    paths, evidence, generation, parties, accounts, _ = _active_repository(tmp_path)
    repository_paths = paths.generation(generation)
    artifact = SourceObjectStore(repository_paths).publish(io.BytesIO(b"retained after rollback"))
    service = MutationService(paths, evidence)

    def fail_after_register(context: Any) -> MutationOutcome:
        context.register_source_artifact(artifact)
        _ownership_handler(
            account_id=accounts[0],
            party_id=parties[0],
            assertion_id=new_entity_id(),
            value_id=new_entity_id(),
        )(context)
        raise OSError("injected after immutable publication")

    with pytest.raises(MutationAbortedError) as captured:
        service.execute(_request(generation, "retained", 0), fail_after_register)

    assert captured.value.retained_artifacts == (artifact.artifact_id,)
    assert (
        repository_paths.root / artifact.relative_path
    ).read_bytes() == b"retained after rollback"
    with sqlite3.connect(repository_paths.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM source_artifacts WHERE source_artifact_id = ?",
            (artifact.artifact_id,),
        ).fetchone() == (0,)
    assert _revision(repository_paths.database) == 0


# Multiprocessing targets use primitive arguments so spawn can serialize them reliably.
def _concurrent_writer(  # noqa: PLR0913
    control_root: str,
    generations_root: str,
    generation: str,
    account_id: str,
    party_id: str,
    key: str,
    assertion_id: str,
    value_id: str,
    start: Any,
    results: Any,
) -> None:
    paths = AuthorityPaths(Path(control_root), Path(generations_root))
    service = MutationService(paths, _evidence())
    start.wait(10)
    try:
        receipt = service.execute(
            _request(generation, key, 0),
            _ownership_handler(
                account_id=account_id,
                party_id=party_id,
                assertion_id=assertion_id,
                value_id=value_id,
            ),
        )
        results.put(("committed", receipt.committed_revision))
    except (MutationConflictError, AuthorityConflictError) as exc:
        results.put(("conflict", type(exc).__name__))


def test_two_subprocess_writers_at_same_revision_commit_exactly_once(tmp_path: Path) -> None:
    paths, _, generation, parties, accounts, _ = _active_repository(tmp_path)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_writer,
            args=(
                str(paths.control_root),
                str(paths.generations_root),
                generation,
                accounts[index],
                parties[index],
                f"writer-{index}",
                new_entity_id(),
                new_entity_id(),
                start,
                results,
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    outcomes = sorted(results.get(timeout=2) for _ in processes)

    assert [status for status, _ in outcomes] == ["committed", "conflict"]
    assert _revision(paths.generation(generation).database) == 1
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM changesets").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
