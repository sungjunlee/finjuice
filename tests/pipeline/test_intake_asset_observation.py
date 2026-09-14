"""Persisted synthetic intake creates exact, source-linked canonical asset observations."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.sqlite import ResourceRecord, SourceObjectStore, new_entity_id
from finjuice.pipeline.storage.sqlite.asset_meanings import AssetMeaningDecision
from finjuice.pipeline.storage.sqlite.backup import create_backup
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand
from finjuice.pipeline.storage.sqlite.exact_import.handler import apply_exact_import
from finjuice.pipeline.storage.sqlite.inactive_restore import restore_workspace
from finjuice.pipeline.storage.sqlite.intake_submission import submit_intake
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationRequest
from tests.pipeline.test_canonical_intake_submission import (  # noqa: F401
    NOW,
    _submission,
    repository,
)
from tests.pipeline.test_sqlite_exact_import import _asset_book, _capture

AMOUNT = "123456789012345678901234567890.00000000000000000001"
IMAGE = b"\x89PNG\r\n\x1a\nsynthetic preserved screenshot bytes"


@pytest.fixture
def asset_repo(repository):  # noqa: F811 - Imported pytest fixture.
    paths, generation, service, account, _ = repository
    resource = new_entity_id()
    request = MutationRequest("synthetic.resource", "resource", {}, generation, 0, "synthetic")

    def add(context):
        context.add_resource(ResourceRecord(resource, "currency", "synthetic"))
        return MutationOutcome({})

    service.execute(request, add)
    return paths, generation, service, account, resource


def _apply(repo, key: str, *, amount: Any = AMOUNT, changes=None):
    paths, generation, service, account, resource = repo
    with sqlite3.connect(paths.generation(generation).database) as connection:
        revision = connection.execute("SELECT dataset_revision FROM repository_meta").fetchone()[0]
    decision = {
        "account_id": account,
        "resource_id": resource,
        "field": "amount",
        "as_of": "2026-09-01",
        "scope_state": "partial",
        "measure_kind": "valuation",
        "currency": "KRW",
        "net_worth_sign": 1,
        "evidence": {"review": "human"},
    }
    decision.update(changes or {})
    proposal = {
        "change_kind": "account_fact",
        "operation": "asset_observation",
        "decision": decision,
    }
    submission = _submission(
        generation,
        source_kind="screenshot",
        content=IMAGE,
        media_type="image/png",
        extraction={"amount": amount, "account_name": "not an identity"},
        proposal=proposal,
        idempotency_key=key,
        expected_revision=revision,
    )
    submitted = submit_intake(service, submission)
    result = submitted.result
    request = MutationRequest(
        result["application_scope"],
        result["application_key"],
        proposal,
        generation,
        result["expected_revision"],
        "synthetic",
    )

    def apply(context):
        return MutationOutcome(context.apply_intake_decision(result["proposal_id"], request, NOW))

    applied = service.execute(request, apply)
    assert service.execute(request, apply).replayed
    return applied, submission, submitted


def test_confirm_dedup_xlsx_preservation_and_actual_restore(asset_repo, tmp_path: Path):
    paths, generation, service, _, _ = asset_repo
    first, _, submitted = _apply(asset_repo, "first")
    second, _, _ = _apply(asset_repo, "different-tool-key")
    original = first.result["applied"]
    assert not original["reused"] and second.result["applied"]["reused"]
    assert second.result["applied"]["assertion_id"] == original["assertion_id"]
    database = paths.generation(generation).database
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM asset_snapshots").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM asset_meaning_assertions").fetchone()[0] == 1
        )
        assert (
            connection.execute(
                "SELECT changeset_id FROM agent_intake_applications WHERE proposal_id=?",
                (submitted.result["proposal_id"],),
            ).fetchone()[0]
            == first.changeset_id
        )
        assert (
            connection.execute(
                "SELECT created_changeset_id FROM asset_meaning_assertions WHERE assertion_id=?",
                (original["assertion_id"],),
            ).fetchone()[0]
            == first.changeset_id
        )
        revision = connection.execute("SELECT dataset_revision FROM repository_meta").fetchone()[0]
    command = ExactImportCommand(_capture(_asset_book()))
    service.execute(
        MutationRequest("synthetic.xlsx", "later-xlsx", {}, generation, revision, "synthetic"),
        lambda context: apply_exact_import(context, command),
    )
    create_backup(database, tmp_path / "backup")
    restored = restore_workspace(tmp_path / "backup", tmp_path / "restore")
    restored_database = restored.workspace / "generation" / "finjuice.sqlite3"
    with sqlite3.connect(restored_database) as connection:
        assert connection.execute("SELECT count(*) FROM asset_snapshots").fetchone()[0] > 1
        assert (
            connection.execute(
                "SELECT lexical FROM exact_values WHERE value_id=?", (original["value_id"],)
            ).fetchone()[0]
            == AMOUNT
        )
        artifact = connection.execute(
            "SELECT o.source_artifact_id FROM asset_snapshots a JOIN record_provenance p "
            "ON p.provenance_id=a.provenance_id JOIN source_occurrences o "
            "ON o.entity_id=p.source_occurrence_id WHERE a.entity_id=?",
            (original["source_entity_id"],),
        ).fetchone()[0]
    from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

    source = SourceObjectStore(GenerationPaths(restored.workspace / "generation")).verify(artifact)
    assert (restored.workspace / "generation" / source.relative_path).read_bytes() == IMAGE


@pytest.mark.parametrize(
    "amount,changes",
    [
        (1.25, {}),
        ("NaN", {}),
        ("Infinity", {}),
        (True, {}),
        (AMOUNT, {"field": "missing"}),
        (AMOUNT, {"account_id": "not an identity"}),
        (AMOUNT, {"resource_id": new_entity_id()}),
        (AMOUNT, {"net_worth_sign": True}),
    ],
)
def test_invalid_extraction_or_inferred_identity_never_creates_observation(
    asset_repo,
    amount,
    changes,
):
    with pytest.raises(MutationValidationError):
        _apply(asset_repo, "invalid", amount=amount, changes=changes)
    paths, generation, *_ = asset_repo
    with sqlite3.connect(paths.generation(generation).database) as connection:
        assert connection.execute("SELECT count(*) FROM asset_snapshots").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM agent_intake_applications").fetchone()[0] == 0
        )


def test_retransmission_cannot_undo_explicit_meaning_correction(asset_repo):
    first, _, _ = _apply(asset_repo, "first")
    paths, generation, service, account, resource = asset_repo
    result = first.result["applied"]
    command = AssetMeaningDecision(
        source_entity_id=result["source_entity_id"],
        value_id=result["value_id"],
        account_id=account,
        resource_id=resource,
        measure_kind="valuation",
        source_kind="screenshot",
        as_of="2026-09-01",
        scope_state="complete",
        evidence={"review": "corrected human meaning"},
        original_currency="KRW",
        supersedes_assertion_id=result["assertion_id"],
    )
    with sqlite3.connect(paths.generation(generation).database) as connection:
        revision = connection.execute("SELECT dataset_revision FROM repository_meta").fetchone()[0]
    request = MutationRequest(
        "synthetic.correction", "correction", {}, generation, revision, "human"
    )
    service.execute(
        request, lambda context: MutationOutcome(context.confirm_asset_meaning(command))
    )
    with pytest.raises(MutationConflictError):
        _apply(asset_repo, "old-evidence-retransmitted")
