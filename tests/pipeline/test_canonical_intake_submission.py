"""Synthetic durable evidence intake and explicit application integration."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.authority import ActivationEvidence, AuthorityPaths
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    PartyRecord,
    RepositoryBuilder,
    SourceObjectStore,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError
from finjuice.pipeline.storage.sqlite.intake_queries import intake_decision_view
from finjuice.pipeline.storage.sqlite.intake_submission import IntakeSubmission, submit_intake
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationOutcome,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION

NOW = "2026-09-14T00:00:00Z"


@pytest.fixture
def repository(tmp_path: Path) -> tuple[AuthorityPaths, str, MutationService, str, str]:
    paths = AuthorityPaths(tmp_path / "control", tmp_path / "generations")
    generation, account, party = new_entity_id(), new_entity_id(), new_entity_id()
    with RepositoryBuilder(paths.generation(generation), generation) as builder:
        builder.add_account(AccountRecord(account_id=account, account_kind="bank.v1"))
        builder.add_party(PartyRecord(party_id=party, party_kind="person"))
        builder.finalize()
    with sqlite3.connect(paths.generation(generation).database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    evidence = ActivationEvidence("0.7.3", "a" * 64, "b" * 64, "c" * 64)
    paths.control_root.mkdir(mode=0o700, parents=True)
    paths.activation.write_text(
        json.dumps(
            {
                "activation_schema_version": 1,
                "release_version": "0.7.3",
                "release_artifact_sha256": "a" * 64,
                "dataset_generation": generation,
                "sqlite_schema_version": SQLITE_SCHEMA_VERSION,
                "dataset_revision": 0,
                "migration_manifest_sha256": "b" * 64,
                "pre_cutover_backup_manifest_sha256": "c" * 64,
                "activated_at": NOW,
            }
        )
    )
    return paths, generation, MutationService(paths, evidence), account, party


def _submission(generation: str, **overrides: Any) -> IntakeSubmission:
    request = IntakeSubmission(
        source_kind="description",
        content="보존할 원문\n".encode(),
        media_type="text/plain",
        channel="synthetic",
        received_at=NOW,
        extractor="synthetic.v1",
        extraction={"text": "extracted separately", "amount": "1.00000000000000000001"},
        proposal_scope="agent.intake.account",
        proposal={
            "change_kind": "account_fact",
            "operation": "ownership",
            "decision": {},
        },
        policy_version="synthetic.v1",
        idempotency_key="submit-one",
        expected_generation=generation,
        expected_revision=0,
        actor="synthetic",
    )
    return replace(request, **overrides)


def _connect(paths: AuthorityPaths, generation: str) -> sqlite3.Connection:
    connection = sqlite3.connect(
        paths.generation(generation).database.as_uri() + "?mode=ro", uri=True
    )
    connection.execute("BEGIN")
    return connection


@pytest.mark.parametrize(
    "kind,content,media",
    [
        ("description", b"literal description\r\n", "text/plain"),
        ("screenshot", b"synthetic image original bytes", "image/png"),
        ("xlsx", b"synthetic workbook original bytes", "application/vnd.openxmlformats"),
    ],
)
def test_original_extraction_proposal_retry_and_new_occurrence(
    repository: tuple[AuthorityPaths, str, MutationService, str, str],
    kind: Any,
    content: bytes,
    media: str,
) -> None:
    paths, generation, service, _, _ = repository
    request = _submission(generation, source_kind=kind, content=content, media_type=media)
    first = submit_intake(service, request)
    retry = submit_intake(service, request)
    assert retry.replayed and retry.changeset_id == first.changeset_id
    assert retry.result == first.result
    assert first.result["expected_revision"] == 1
    artifact = SourceObjectStore(paths.generation(generation)).verify(
        first.result["source_artifact_id"]
    )
    assert (paths.generation(generation).root / artifact.relative_path).read_bytes() == content
    connection = _connect(paths, generation)
    try:
        view = intake_decision_view(connection)
        decision = view["decisions"][0]
        assert decision["status"] == "pending" and not decision["stale"]
        assert decision["extraction"] == request.extraction
        assert decision["proposal"] == request.proposal
        second = submit_intake(
            service, replace(request, idempotency_key="submit-two", expected_revision=1)
        )
        assert second.result["intake_artifact_id"] == first.result["intake_artifact_id"]
        assert second.result["occurrence_id"] != first.result["occurrence_id"]
        assert intake_decision_view(connection) == view
    finally:
        connection.close()
    with _connect(paths, generation) as connection:
        view = intake_decision_view(connection)
        assert view["dataset_revision"] == 2
        assert {item["status"] for item in view["decisions"]} == {"pending", "stale"}
        assert connection.execute("SELECT count(*) FROM source_artifacts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM agent_intake_artifacts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM agent_intake_occurrences").fetchone()[0] == 2
        )


def test_identity_conflicts_uncertainties_and_snapshot_requirement(
    repository: tuple[AuthorityPaths, str, MutationService, str, str],
) -> None:
    paths, generation, service, _, _ = repository
    request = _submission(generation, uncertainties=("account_mapping_unknown",))
    submit_intake(service, request)
    for changed in (
        replace(request, content=b"changed evidence"),
        replace(request, proposal={"changed": True}),
        replace(request, extraction={"changed": True}),
        replace(request, idempotency_key="new", expected_revision=0),
        replace(request, idempotency_key="new", expected_generation=new_entity_id()),
    ):
        with pytest.raises(MutationConflictError):
            submit_intake(service, changed)
    with _connect(paths, generation) as connection:
        view = intake_decision_view(connection)
        assert view["dataset_revision"] == 1
        assert view["decisions"][0]["status"] == "uncertain"
        assert view["decisions"][0]["uncertainties"] == ["account_mapping_unknown"]
        connection.rollback()
        with pytest.raises(ValueError, match="snapshot"):
            intake_decision_view(connection)


def test_submission_actual_ownership_application_retry_and_evidence_resubmission(
    repository: tuple[AuthorityPaths, str, MutationService, str, str],
) -> None:
    paths, generation, service, account, party = repository
    proposal = {
        "change_kind": "account_fact",
        "operation": "ownership",
        "decision": {
            "account_id": account,
            "completeness": "complete",
            "shares": [{"party_id": party, "coefficient": "1", "scale": 0}],
            "evidence": {"operator": "synthetic explicit ownership"},
        },
    }
    request = _submission(generation, proposal=proposal)
    submitted = submit_intake(service, request)
    receipt = submitted.result
    application = MutationRequest(
        command_scope=receipt["application_scope"],
        idempotency_key=receipt["application_key"],
        payload=proposal,
        expected_generation=receipt["expected_generation"],
        expected_revision=receipt["expected_revision"],
        actor="synthetic",
    )

    def apply(context: Any) -> MutationOutcome:
        return MutationOutcome(
            context.apply_intake_decision(receipt["proposal_id"], application, NOW)
        )

    applied = service.execute(application, apply)
    replayed = service.execute(application, apply)
    assert replayed.replayed and replayed.result == applied.result
    assert replayed.changeset_id == applied.changeset_id
    with pytest.raises(MutationConflictError):
        service.execute(replace(application, payload={"different": True}), apply)
    assert submit_intake(service, request).replayed
    submit_intake(service, replace(request, idempotency_key="reimport", expected_revision=2))
    with _connect(paths, generation) as connection:
        assert (
            connection.execute("SELECT count(*) FROM ownership_assertion_sets").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT count(*) FROM agent_intake_applications").fetchone()[0] == 1
        )
        decisions = intake_decision_view(connection)["decisions"]
        old = next(item for item in decisions if item["proposal_id"] == receipt["proposal_id"])
        assert old["status"] == "applied"
        assert old["application"]["changeset_id"] == applied.changeset_id
        assert old["proposal"] == proposal
