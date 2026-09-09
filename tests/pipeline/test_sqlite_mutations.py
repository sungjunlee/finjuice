"""Focused synthetic tests for schema v2 authority and atomic mutations."""

from __future__ import annotations

import io
import json
import multiprocessing
import sqlite3
from pathlib import Path
from typing import Any, Literal

import pytest

from finjuice.pipeline.storage import authority as authority_module
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    LegacyAuthority,
    RepositoryAuthority,
    exclusive_maintenance_lease,
    require_legacy_authority,
    resolve_authority,
    shared_write_lease,
)
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    AgentIntakeApplicationRecord,
    AgentIntakeArtifactRecord,
    AgentIntakeConfirmationRecord,
    AgentIntakeExtractionRecord,
    AgentIntakeOccurrenceRecord,
    AgentIntakeProposalRecord,
    EntityRelationAssertionRecord,
    ExactValue,
    MutationAbortedError,
    MutationConflictError,
    MutationValidationError,
    OwnershipAssertionRecord,
    OwnershipShareRecord,
    PartyRecord,
    RepositoryBuilder,
    RepositoryIntegrityError,
    SourceObjectStore,
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
    MutationOutcome,
    MutationRequest,
    MutationService,
)

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
        "sqlite_schema_version": 2,
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


def test_fresh_schema_runs_v1_then_v2_and_v1_upgrade_preserves_source(tmp_path: Path) -> None:
    fresh = schema_module.GenerationPaths(tmp_path / "fresh")
    with RepositoryBuilder(fresh, new_entity_id()) as builder:
        builder.finalize()
    with sqlite3.connect(fresh.database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute(
            "SELECT schema_version FROM schema_migrations ORDER BY schema_version"
        ).fetchall() == [(1,), (2,)]

    source = schema_module.GenerationPaths(tmp_path / "v1-source")
    schema_module._prepare_generation_layout(source)
    source_connection = schema_module._connect_builder(source.database)
    generation = new_entity_id()
    try:
        schema_module._apply_schema_v1(source_connection, generation)
    finally:
        source_connection.close()
    source_before = source.database.read_bytes()
    destination = schema_module.GenerationPaths(tmp_path / "upgraded")

    upgraded = upgrade_repository(source.database, destination)

    assert upgraded.schema_version == 2
    assert upgraded.dataset_generation == generation
    assert source.database.read_bytes() == source_before
    with sqlite3.connect(destination.database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM schema_migrations ORDER BY schema_version"
        ).fetchall() == [(1,), (2,)]


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
            payload=payload,
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


def test_intake_requires_matching_confirmed_payload_and_preserves_lineage(tmp_path: Path) -> None:
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

    with pytest.raises(AuthorityIntegrityError, match="unsupported"):
        with shared_write_lease(paths):
            pytest.fail("unsupported lease was acquired")


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
