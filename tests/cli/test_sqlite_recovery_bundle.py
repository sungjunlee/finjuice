"""Operator CLI for local recovery-graph capture, verify, and inactive restore."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import sqlite_backup
from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    RestoredWorkspaceReceipt,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    ExpectedRecoveryGraph,
    RecoveryCaptureInput,
)
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.pipeline.test_inactive_restore import _manual
from tests.pipeline.test_recovery_bundle import _live
from tests.pipeline.test_sqlite_mutations import _request

runner = CliRunner()
_RECEIPT_FIELDS = (
    "restore_id",
    "descriptor_digest",
    "dataset_generation",
    "initial_database_digest",
    "source_manifest_digest",
    "initial_dataset_revision",
    "sqlite_schema_version",
)


def _invoke(active: Path, *args: str):
    return runner.invoke(app, ["--data-dir", str(active), "ssot", "backup", *args])


def _document(expected: ExpectedRecoveryGraph) -> dict:
    evidence = asdict(expected.activation_evidence)
    return {
        "activation_evidence": evidence,
        "activation_sha256": expected.activation_sha256,
        "release": {
            "binding_sha256": expected.release.binding_sha256,
            "activation_evidence": asdict(expected.release.activation_evidence),
        },
        "capsule": {
            "activation_evidence": asdict(expected.capsule.activation_evidence),
            "migration_semantics": expected.capsule.migration_semantics,
            "pre_cutover_semantics": expected.capsule.pre_cutover_semantics,
        },
        "wheel_basename": expected.wheel_basename,
    }


def _write_expected(path: Path, expected: ExpectedRecoveryGraph) -> Path:
    path.write_text(json.dumps(_document(expected)), encoding="utf-8")
    return path


def _capture_args(source: RecoveryCaptureInput, expected_path: Path) -> list[str]:
    paths = source.release_paths
    return [
        "capture-bundle",
        "--source-data-dir",
        str(source.data_dir),
        "--output",
        str(source.destination),
        "--expected",
        str(expected_path),
        "--wheel",
        str(paths.wheel),
        "--dependency-lock",
        str(paths.dependency_lock),
        "--binding",
        str(paths.binding),
        "--migration-candidate",
        str(source.migration_candidate),
    ]


def _minimal_expected() -> dict:
    digest = "a" * 64
    evidence = {
        "installed_release_version": "1.2.3",
        "installed_release_artifact_sha256": digest,
        "verified_migration_manifest_sha256": digest,
        "verified_pre_cutover_backup_manifest_sha256": digest,
    }
    return {
        "activation_evidence": evidence,
        "activation_sha256": digest,
        "release": {"binding_sha256": digest, "activation_evidence": dict(evidence)},
        "capsule": {
            "activation_evidence": dict(evidence),
            "migration_semantics": "raw_file_sha256",
            "pre_cutover_semantics": "canonical_manifest_digest",
        },
        "wheel_basename": "finjuice-1.2.3-py3-none-any.whl",
    }


@pytest.mark.parametrize("machine", [True, False])
def test_capture_verify_inactive_restore_after_source_removal(
    tmp_path: Path, machine: bool
) -> None:
    source, expected, paths, generation, transactions, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    flags = ["--json"] if machine else []
    active = tmp_path / "active"
    captured = _invoke(active, *_capture_args(source, expected_path), *flags)
    assert captured.exit_code == 0, captured.output
    assert str(tmp_path) not in captured.output
    if machine:
        payload = json.loads(captured.output)
        _validate_command_schema(
            payload,
            command="ssot backup capture-bundle",
            schema_file="ssot_backup_capture_bundle.schema.json",
        )
        assert payload["kind"] == "local_graph_verified"
        assert payload["snapshot_revision"] > payload["activation_revision"]
        snapshot_manifest_digest = payload["snapshot_manifest_digest"]
    else:
        assert "Local recovery graph verified" in captured.output
    source_bytes = paths.generation(generation).database.read_bytes()
    shutil.rmtree(tmp_path / "synth")
    shutil.rmtree(source.data_dir)
    shutil.rmtree(source.release_paths.wheel.parent)
    verified = _invoke(
        active, "verify-bundle", str(source.destination), "--expected", str(expected_path), *flags
    )
    assert verified.exit_code == 0, verified.output
    assert str(tmp_path) not in verified.output
    if machine:
        payload = json.loads(verified.output)
        _validate_command_schema(
            payload,
            command="ssot backup verify-bundle",
            schema_file="ssot_backup_verify_bundle.schema.json",
        )
    workspace = tmp_path / "workspace"
    restored = _invoke(
        active,
        "restore-bundle",
        str(source.destination),
        "--target",
        str(workspace),
        "--expected",
        str(expected_path),
        *flags,
    )
    assert restored.exit_code == 0, restored.output
    assert str(tmp_path) not in restored.output
    if machine:
        payload = json.loads(restored.output)
    else:
        from tests.conftest import cli_text

        payload, _ = json.JSONDecoder().raw_decode("{" + cli_text(restored).split("{", 1)[1])
    _validate_command_schema(
        payload,
        command="ssot backup restore-bundle",
        schema_file="ssot_backup_restore_bundle.schema.json",
    )
    if machine:
        assert payload["source_manifest_digest"] == snapshot_manifest_digest
    for field in _RECEIPT_FIELDS:
        assert field in payload
    receipt = RestoredWorkspaceReceipt(
        workspace, **{key: value for key, value in payload.items() if key != "_meta"}
    )
    _mutate_and_rebackup(receipt, transactions, tmp_path)
    assert source_bytes
    assert not (tmp_path / "data").exists()
    assert (workspace / "generation" / "finjuice.sqlite3").is_file()
    assert not (workspace / ".finjuice" / "authority" / "active.json").exists()


def _mutate_and_rebackup(
    receipt: RestoredWorkspaceReceipt, transactions: list[dict], tmp_path: Path
) -> None:
    with InactiveRestoreSession(receipt) as session:
        if transactions:
            edited = session.execute(
                _request(
                    receipt.dataset_generation,
                    "restored-manual",
                    receipt.initial_dataset_revision,
                    scope="transaction.manual_edit",
                ),
                _manual(transactions[0]["entity_id"]),
            )
        else:
            from finjuice.pipeline.storage.sqlite import PartyRecord, new_entity_id
            from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome

            def add_party(context):
                party_id = new_entity_id()
                context.add_party(PartyRecord(party_id))
                return MutationOutcome(result={"party_id": party_id})

            edited = session.execute(
                _request(
                    receipt.dataset_generation, "restored-party", receipt.initial_dataset_revision
                ),
                add_party,
            )
        assert edited.committed_revision == receipt.initial_dataset_revision + 1
        second = session.backup(tmp_path / "rebackup")
        assert second.dataset_revision == edited.committed_revision


def test_restore_bundle_rejects_active_overlap_before_mutation(tmp_path: Path) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    captured = _invoke(tmp_path / "active", *_capture_args(source, expected_path), "--json")
    assert captured.exit_code == 0, captured.output
    active = tmp_path / "active"
    result = _invoke(
        active,
        "restore-bundle",
        str(source.destination),
        "--target",
        str(active),
        "--expected",
        str(expected_path),
        "--json",
    )
    assert result.exit_code != 0
    assert not (active / "generation").exists()
    assert str(tmp_path) not in result.output
    assert json.loads(result.output)["error"]


def test_invalid_config_cannot_bypass_restore_bundle_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    captured = _invoke(tmp_path / "active", *_capture_args(source, expected_path), "--json")
    assert captured.exit_code == 0, captured.output

    def invalid_config():
        raise ValueError(f"PRIVATE_CONFIGURATION {tmp_path}")

    monkeypatch.setattr(sqlite_backup, "load_config", invalid_config)
    result = _invoke(
        tmp_path / "active",
        "restore-bundle",
        str(source.destination),
        "--target",
        str(tmp_path / "target"),
        "--expected",
        str(expected_path),
        "--json",
    )
    assert result.exit_code != 0
    assert "PRIVATE_CONFIGURATION" not in result.output
    assert str(tmp_path) not in result.output
    assert not (tmp_path / "target").exists()


def test_verify_rejects_expectation_not_taken_from_bundle(tmp_path: Path) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    captured = _invoke(tmp_path / "active", *_capture_args(source, expected_path), "--json")
    assert captured.exit_code == 0, captured.output
    wrong = _document(expected)
    wrong["activation_sha256"] = "0" * 64
    wrong_path = tmp_path / "wrong.json"
    wrong_path.write_text(json.dumps(wrong), encoding="utf-8")
    result = _invoke(
        tmp_path / "active",
        "verify-bundle",
        str(source.destination),
        "--expected",
        str(wrong_path),
        "--json",
    )
    assert result.exit_code != 0
    assert str(tmp_path) not in result.output


@pytest.mark.parametrize(
    "tamper",
    ["duplicate", "extra", "bool"],
)
def test_expected_json_rejects_duplicate_extra_and_wrong_types(tmp_path: Path, tamper: str) -> None:
    document = _minimal_expected()
    path = tmp_path / "expected.json"
    if tamper == "duplicate":
        path.write_text(
            '{"wheel_basename": "finjuice-1.2.3-py3-none-any.whl",'
            ' "wheel_basename": "finjuice-1.2.3-py3-none-any.whl"}',
            encoding="utf-8",
        )
    elif tamper == "extra":
        document["unexpected"] = "no"
        path.write_text(json.dumps(document), encoding="utf-8")
    else:
        document["wheel_basename"] = True
        path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(BackupVerificationError):
        load_expected_recovery_graph(path)


def test_manifest_recovery_bundle_policy() -> None:
    result = runner.invoke(app, ["manifest", "--json"])
    assert result.exit_code == 0
    commands = {item["path"]: item for item in json.loads(result.output)["commands"]}
    for action, mutating in (
        ("capture-bundle", True),
        ("verify-bundle", False),
        ("restore-bundle", True),
        ("create", True),
        ("status", False),
        ("restore", True),
        ("store init", True),
        ("store capture", True),
        ("store list", False),
        ("store verify", False),
        ("store restore", True),
        ("store protect", True),
        ("store plan", False),
        ("store prune", True),
    ):
        policy = commands[f"ssot backup {action}"]
        assert policy["mutates_data"] is mutating
        assert policy["safe_readonly"] is not mutating
        assert policy["privacy_profile"] == "artifact_path"
        schema = f"schemas/ssot_backup_{action.replace('-', '_').replace(' ', '_')}.schema.json"
        assert policy["output_schema_ref"] == schema


@pytest.mark.parametrize("same_generation", [True, False])
def test_restore_bundle_rejects_a_different_valid_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_generation: bool
) -> None:
    from finjuice.pipeline.cli.commands import sqlite_recovery_bundle as cli_module
    from finjuice.pipeline.storage.sqlite.backup import create_backup
    from finjuice.pipeline.storage.sqlite.recovery_bundle import capture_recovery_bundle

    source, expected, paths, generation, *_ = _live(tmp_path)
    expected_path = _write_expected(tmp_path / "enrolled.json", expected)
    verified = capture_recovery_bundle(source, expected)
    alternative = tmp_path / "alternative"
    if same_generation:
        database = paths.generation(generation).database
    else:
        other = tmp_path / "other"
        other.mkdir()
        _, _, other_paths, other_generation, *_ = _live(other)
        database = other_paths.generation(other_generation).database
    alternate = create_backup(database, alternative)
    assert alternate.manifest_digest != verified.snapshot_manifest_digest
    original_database = paths.generation(generation).database.read_bytes()
    original_activation = paths.activation.read_bytes()
    real_restore = cli_module.restore_workspace
    receipts = []

    def restore_alternative(_backup: Path, target: Path):
        receipt = real_restore(alternative, target)
        receipts.append(receipt)
        return receipt

    monkeypatch.setattr(cli_module, "restore_workspace", restore_alternative)
    result = _invoke(
        tmp_path / "active",
        "restore-bundle",
        str(source.destination),
        "--target",
        str(tmp_path / "workspace"),
        "--expected",
        str(expected_path),
        "--json",
    )

    assert len(receipts) == 1
    assert receipts[0].source_manifest_digest == alternate.manifest_digest
    if same_generation:
        assert receipts[0].dataset_generation == verified.snapshot_generation
        assert receipts[0].initial_dataset_revision == verified.snapshot_revision
    else:
        assert receipts[0].dataset_generation != verified.snapshot_generation
    assert result.exit_code != 0, result.output
    payload = json.loads(result.output)
    assert "restore_id" not in payload
    assert paths.generation(generation).database.read_bytes() == original_database
    assert paths.activation.read_bytes() == original_activation
    assert not (tmp_path / "workspace" / ".finjuice").exists()
