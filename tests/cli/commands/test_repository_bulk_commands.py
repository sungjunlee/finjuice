"""Active bulk commands must use canonical state and durable mutation receipts."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import (
    compute_full_pipeline_tag,
    compute_full_pipeline_transfer,
)
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import ConfigDocument
from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationContext,
    MutationOutcome,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import SourceOccurrenceRecord
from tests.cli.commands.test_repository_mutation_fences import (
    _ActiveRoot,
    _authority_state,
)
from tests.cli.commands.test_repository_mutation_fences import (
    active_root as _active_root_fixture,
)
from tests.pipeline.test_sqlite_bulk_mutations import _add_transaction, _Maps, _Txn
from tests.pipeline.test_sqlite_typed_mutations import (
    _new_ids,
    _write_foundation,
    _write_transaction,
)

active_root = _active_root_fixture


def _invoke(active: _ActiveRoot, command: str, *args: str):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(active.root), command, *args],
        obj={"activation_evidence_provider": active.provider},
    )


def _rules(active: _ActiveRoot) -> None:
    active.facade.replace_config(
        ConfigDocument.from_validated_yaml(
            "rules",
            b"version: 1\nrules:\n  - name: cafe\n    match: cafe\n"
            b"    fields: [merchant_raw]\n    tags: [coffee]\n    priority: 10\n",
            parser_version="finjuice.rules.v1",
        )
    )


def _seed_transaction(active: _ActiveRoot) -> str:
    ids = _new_ids()

    def handler(context: MutationContext) -> MutationOutcome:
        artifact = SourceObjectStore(context.authority.paths).publish(io.BytesIO(b"synthetic"))
        context.retain_artifact(artifact.artifact_id)
        context.register_source_artifact(artifact)
        _write_foundation(context, artifact.artifact_id, ids)
        _write_transaction(context, ids)
        return MutationOutcome(result={"transaction_id": ids.transaction})

    MutationService(active.paths, active.evidence).execute(
        MutationRequest(
            command_scope="test.bulk_cli_seed",
            idempotency_key="seed",
            payload={},
            expected_generation=active.generation,
            expected_revision=0,
            actor="test",
        ),
        handler,
    )
    return ids.transaction


@pytest.mark.parametrize("command", ["tag", "transfer"])
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_bulk_preview_preserves_database_objects_and_legacy_files(
    active_root: _ActiveRoot, command: str, json_output: bool
) -> None:
    _seed_transaction(active_root)
    _rules(active_root)
    before = _authority_state(active_root)

    result = _invoke(active_root, command, "--dry-run", *(["--json"] if json_output else []))

    assert result.exit_code == ExitCode.SUCCESS, result.output
    if json_output:
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["authority"] == "repository"
        assert data["state_changed"] is False
        assert data["dataset_revision"] == 2
        if command == "tag":
            assert (data["total"], data["tagged"], data["untagged"]) == (1, 1, 0)
            assert data["coverage_pct"] == 100.0
    else:
        assert "Dry-run Summary" in result.output
        assert "No changes written" in result.output
        assert "detection complete" not in result.output
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("command", ["tag", "transfer"])
def test_bulk_explicit_replay_survives_later_opaque_rules_head(
    active_root: _ActiveRoot, command: str
) -> None:
    _seed_transaction(active_root)
    _rules(active_root)
    args = (
        "--json",
        "--idempotency-key",
        f"stable-{command}",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        "2",
    )
    first = _invoke(active_root, command, *args)
    assert first.exit_code == ExitCode.SUCCESS, first.output
    committed = json.loads(first.output)
    active_root.facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=b"- opaque source\n",
            parsed_status="opaque",
            canonical_payload=None,
            parser_version="synthetic.opaque.v1",
        )
    )
    before = _authority_state(active_root)

    replay = _invoke(active_root, command, *args)

    assert replay.exit_code == ExitCode.SUCCESS, replay.output
    data = json.loads(replay.output)
    assert data["replayed"] is True
    assert data["changeset_id"] == committed["changeset_id"]
    assert data["committed_revision"] == committed["committed_revision"]
    assert _authority_state(active_root) == before
    assert (active_root.root / "rules.yaml").read_bytes() == b"legacy sentinel unchanged\n"


@pytest.mark.parametrize("command", ["tag", "transfer"])
def test_bulk_stale_revision_fails_cleanly_without_mutation(
    active_root: _ActiveRoot, command: str
) -> None:
    _rules(active_root)
    before = _authority_state(active_root)

    result = _invoke(active_root, command, "--json", "--expected-revision", "0")

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    data = json.loads(result.output)
    assert data["error"]["code"] == ErrorCode.VALIDATION_FAILED
    assert "revision is stale" in data["error"]["message"]
    assert _authority_state(active_root) == before


def test_bulk_tag_does_not_fall_back_to_legacy_rules(active_root: _ActiveRoot) -> None:
    before = _authority_state(active_root)

    result = _invoke(active_root, "tag", "--json")

    assert result.exit_code != ExitCode.SUCCESS, result.output
    assert "Rules" in json.loads(result.output)["error"]["message"]
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("command", ["tag", "transfer"])
@pytest.mark.parametrize("dry_run", [False, True], ids=["commit", "preview"])
def test_bulk_incomplete_replay_identity_fails_without_writes(
    active_root: _ActiveRoot, command: str, dry_run: bool
) -> None:
    _rules(active_root)
    before = _authority_state(active_root)

    result = _invoke(
        active_root,
        command,
        "--json",
        "--idempotency-key",
        "missing-preconditions",
        *(["--dry-run"] if dry_run else []),
    )

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert (
        "requires expected generation and revision" in json.loads(result.output)["error"]["message"]
    )
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("command", ["tag", "transfer"])
def test_bulk_preview_rejects_stale_snapshot_without_writes(
    active_root: _ActiveRoot, command: str
) -> None:
    _rules(active_root)
    before = _authority_state(active_root)

    result = _invoke(active_root, command, "--json", "--dry-run", "--expected-revision", "0")

    assert result.exit_code == ExitCode.VALIDATION_ERROR, result.output
    assert "revision is stale" in json.loads(result.output)["error"]["message"]
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("dry_run", [False, True], ids=["commit", "preview"])
def test_bulk_tag_rejects_opaque_rules_without_writes(
    active_root: _ActiveRoot, dry_run: bool
) -> None:
    active_root.facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=b"- opaque source\n",
            parsed_status="opaque",
            canonical_payload=None,
            parser_version="synthetic.opaque.v1",
        )
    )
    before = _authority_state(active_root)

    result = _invoke(active_root, "tag", "--json", *(["--dry-run"] if dry_run else []))

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert "parsed canonical" in json.loads(result.output)["error"]["message"]
    assert _authority_state(active_root) == before


def test_legacy_transfer_preview_rejects_before_any_writer(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    root.mkdir()

    result = CliRunner().invoke(app, ["--data-dir", str(root), "transfer", "--dry-run", "--json"])

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert json.loads(result.output)["error"]["code"] == ErrorCode.INVALID_ARGS
    assert not (root / "transactions").exists()


def test_full_pipeline_bulk_steps_use_repository_and_preserve_legacy_files(
    active_root: _ActiveRoot,
) -> None:
    _seed_transaction(active_root)
    _rules(active_root)
    config = Config(data_dir=active_root.root)
    sentinels = {
        name: (active_root.root / name).read_bytes()
        for name in ("rules.yaml", "goals.yaml", "assets.yaml")
    }

    tagged = compute_full_pipeline_tag(config, facade=active_root.facade)
    transferred = compute_full_pipeline_transfer(config, facade=active_root.facade)

    assert tagged["authority"] == transferred["authority"] == "repository"
    assert (tagged["total"], tagged["tagged"]) == (1, 1)
    assert transferred["candidate_rows"] == 0
    assert {name: (active_root.root / name).read_bytes() for name in sentinels} == sentinels
    assert not list((active_root.root / "transactions").rglob("*.csv"))


def test_full_pipeline_skips_absent_rules_but_rejects_opaque_rules(
    active_root: _ActiveRoot,
) -> None:
    config = Config(data_dir=active_root.root)
    before = _authority_state(active_root)

    result = compute_full_pipeline_tag(config, facade=active_root.facade)

    assert result["skipped"] is True
    assert result["authority"] == "repository"
    assert _authority_state(active_root) == before
    active_root.facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=b"- opaque source\n",
            parsed_status="opaque",
            canonical_payload=None,
            parser_version="synthetic.opaque.v1",
        )
    )
    before = _authority_state(active_root)
    with pytest.raises(MutationValidationError, match="parsed canonical"):
        compute_full_pipeline_tag(config, facade=active_root.facade)
    assert _authority_state(active_root) == before


def test_active_refresh_success_does_not_write_legacy_schema_metadata(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.cli.commands import refresh_cmd

    def reject_legacy_metadata(*args, **kwargs):
        pytest.fail("Active refresh touched legacy schema metadata")

    monkeypatch.setattr(refresh_cmd, "warn_on_schema_mismatch", reject_legacy_metadata)
    monkeypatch.setattr(refresh_cmd, "write_schema_version", reject_legacy_metadata)
    monkeypatch.setattr(
        refresh_cmd,
        "_compute_full_pipeline_result",
        lambda *args, **kwargs: {"command": "refresh", "steps": {}},
    )
    before = _authority_state(active_root)

    result = _invoke(active_root, "refresh", "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert json.loads(result.output)["command"] == "refresh"
    assert _authority_state(active_root) == before


def test_bulk_transfer_cli_counts_pairs_separately_from_unconfirmed_candidates(
    active_root: _ActiveRoot,
) -> None:
    ids = _new_ids()

    def seed(context: MutationContext) -> MutationOutcome:
        artifact = SourceObjectStore(context.authority.paths).publish(io.BytesIO(b"pair counts"))
        context.retain_artifact(artifact.artifact_id)
        context.register_source_artifact(artifact)
        context.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=ids.occurrence,
                artifact_id=artifact.artifact_id,
                occurrence_kind="synthetic",
                original_filename="pairs.xlsx",
                imported_at="2026-09-09T00:00:00Z",
            )
        )
        specs = (
            _Txn(
                "out",
                "-100",
                timezone_state="known",
                effective_at="2026-09-01T12:00:00Z",
                type_norm="transfer",
            ),
            _Txn(
                "in",
                "100",
                timezone_state="known",
                effective_at="2026-09-01T12:00:30Z",
                type_norm="transfer",
            ),
            _Txn("unknown-clock", "50", type_norm="transfer"),
        )
        maps = _Maps({}, {})
        for index, spec in enumerate(specs, start=1):
            _add_transaction(context, ids.occurrence, spec, index, maps)
        return MutationOutcome(result={"seeded": len(specs)})

    MutationService(active_root.paths, active_root.evidence).execute(
        MutationRequest(
            command_scope="test.bulk_cli_pairs",
            idempotency_key="seed-pairs",
            payload={},
            expected_generation=active_root.generation,
            expected_revision=0,
            actor="test",
        ),
        seed,
    )
    before = _authority_state(active_root)

    preview = _invoke(active_root, "transfer", "--dry-run", "--json")

    assert preview.exit_code == ExitCode.SUCCESS, preview.output
    planned = json.loads(preview.output)
    assert _authority_state(active_root) == before
    committed = _invoke(active_root, "transfer", "--json")
    assert committed.exit_code == ExitCode.SUCCESS, committed.output
    actual = json.loads(committed.output)
    for field, expected in {
        "candidate_rows": 3,
        "candidates_considered": 2,
        "pairs_found": 1,
        "pairs_linked": 2,
        "confirmed_transfer_rows": 2,
        "unconfirmed_candidate_rows": 1,
    }.items():
        assert planned[field] == actual[field] == expected
