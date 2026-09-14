"""Local recovery graph verifies from the bundle after source removal."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    StaticActivationEvidenceProvider,
)
from finjuice.pipeline.storage.sqlite import (
    ExactValue,
    PartyRecord,
    RepositoryBuilder,
    inspect_repository,
    new_entity_id,
    upgrade_repository,
)
from finjuice.pipeline.storage.sqlite import recovery_bundle as module
from finjuice.pipeline.storage.sqlite.backup import create_backup
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.records import OwnershipAssertionRecord, OwnershipShareRecord
from finjuice.pipeline.storage.sqlite.recovery_migration_capsule import ExpectedMigrationCapsule
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import (
    ReleaseArtifactPaths,
    TrustedReleaseBinding,
)
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader
from tests.pipeline.test_inactive_restore import _manual
from tests.pipeline.test_recovery_migration_capsule import _expected as _capsule_expected
from tests.pipeline.test_recovery_release_evidence import _digest, _wheel
from tests.pipeline.test_sqlite_mutations import _NOW, _request
from tests.pipeline.test_sqlite_portfolio_reads import _candidate


class _FlipProvider:
    def __init__(self, first: ActivationEvidence, second: ActivationEvidence) -> None:
        self.first = first
        self.second = second
        self.calls = 0

    def evidence_for(self, paths: object) -> ActivationEvidence:
        del paths
        self.calls += 1
        return self.first if self.calls == 1 else self.second


def _ownership(account_id: str, party_id: str, assertion_id: str, value_id: str):
    def handler(context):
        context.add_party(PartyRecord(party_id))
        context.add_exact_value(
            value_id,
            ExactValue(
                coefficient="1",
                scale=0,
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
                completeness="complete",
                confirmation_state="confirmed",
                evidence={"kind": "synthetic"},
                unknown_remainder=False,
                confirmed_at=_NOW,
                supersedes_assertion_id=None,
            ),
            [OwnershipShareRecord(assertion_id, party_id, value_id)],
        )
        return MutationOutcome(result={"assertion_id": assertion_id})

    return handler


def _release(tmp_path: Path, evidence: ActivationEvidence, *, version: str = "1.2.3"):
    wheel = _wheel(version=version)
    lock = b"version = 1\n# synthetic dependency lock\n"
    basename = f"finjuice-{version}-py3-none-any.whl"
    binding = {
        "binding_schema_version": 1,
        "package_name": "finjuice",
        "release_version": version,
        "release_artifact_sha256": _digest(wheel),
        "dependency_lock_sha256": _digest(lock),
        "source_commit": "a" * 40,
        "build_id": "approved-build.123",
    }
    raw = json.dumps(binding).encode()
    directory = tmp_path / "release-artifacts"
    directory.mkdir(exist_ok=True)
    paths = ReleaseArtifactPaths(
        directory / basename, directory / "dependency.lock", directory / "binding.json"
    )
    paths.wheel.write_bytes(wheel)
    paths.dependency_lock.write_bytes(lock)
    paths.binding.write_bytes(raw)
    trusted = TrustedReleaseBinding(_digest(raw), evidence)
    return paths, trusted, basename, _digest(wheel)


def _live(tmp_path: Path):
    synth = tmp_path / "synth"
    candidate = _candidate(synth).parent
    capsule = _capsule_expected(candidate)
    version = "1.2.3"
    evidence = ActivationEvidence(
        version,
        "0" * 64,
        capsule.activation_evidence.verified_migration_manifest_sha256,
        capsule.activation_evidence.verified_pre_cutover_backup_manifest_sha256,
    )
    release_paths, trusted, basename, wheel_sha = _release(tmp_path, evidence)
    evidence = replace(evidence, installed_release_artifact_sha256=wheel_sha)
    trusted = TrustedReleaseBinding(trusted.binding_sha256, evidence)
    capsule = ExpectedMigrationCapsule(
        evidence, capsule.migration_semantics, capsule.pre_cutover_semantics
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir(mode=0o700)
    (data_dir / ".finjuice").mkdir(mode=0o700)
    paths = AuthorityPaths.for_data_dir(data_dir)
    info = inspect_repository(candidate / "finjuice.sqlite3", expected_schema_version=5)
    assert info.dataset_generation is not None
    generation = info.dataset_generation
    upgrade_repository(candidate / "finjuice.sqlite3", paths.generation(generation))
    live = inspect_repository(paths.generation(generation).database)
    payload = {
        "activation_schema_version": 1,
        "release_version": version,
        "release_artifact_sha256": wheel_sha,
        "dataset_generation": generation,
        "sqlite_schema_version": live.schema_version,
        "dataset_revision": live.dataset_revision,
        "migration_manifest_sha256": evidence.verified_migration_manifest_sha256,
        "pre_cutover_backup_manifest_sha256": evidence.verified_pre_cutover_backup_manifest_sha256,
        "activated_at": "2026-09-14T00:00:00Z",
    }
    raw = json.dumps(payload).encode()
    paths.control_root.mkdir(parents=True, mode=0o700)
    paths.activation.write_bytes(raw)
    with RepositoryReader(paths.generation(generation).database) as reader:
        account_id = reader.rows("accounts")[0]["entity_id"]
        transactions = reader.rows("transactions")
    MutationService(paths, evidence).execute(
        _request(generation, "post-cutover", 0),
        _ownership(account_id, new_entity_id(), new_entity_id(), new_entity_id()),
    )
    expected = module.ExpectedRecoveryGraph(
        evidence, hashlib.sha256(raw).hexdigest(), trusted, capsule, basename
    )
    source = module.RecoveryCaptureInput(
        data_dir,
        tmp_path / "bundle",
        StaticActivationEvidenceProvider(evidence),
        release_paths,
        candidate,
    )
    return source, expected, paths, generation, transactions, account_id


def test_bundle_survives_source_removal_and_restored_mutation(
    tmp_path: Path,
) -> None:
    source, expected, paths, generation, transactions, _account = _live(tmp_path)
    receipt = module.capture_recovery_bundle(source, expected)
    assert receipt.kind == "local_graph_verified"
    assert receipt.snapshot_revision > receipt.activation_revision
    assert receipt.wheel_basename == expected.wheel_basename
    assert "recoverable" not in receipt.to_dict()
    assert "path" not in repr(receipt)
    source_tree = tmp_path / "synth"
    data_bytes = paths.generation(generation).database.read_bytes()
    shutil.rmtree(source_tree)
    shutil.rmtree(source.data_dir)
    shutil.rmtree(source.release_paths.wheel.parent)
    assert module.verify_recovery_bundle(source.destination, expected) == receipt
    workspace = restore_workspace(source.destination / "snapshot", tmp_path / "workspace")
    with InactiveRestoreSession(workspace) as session:
        if transactions:
            edited = session.execute(
                _request(
                    generation,
                    "restored-manual",
                    receipt.snapshot_revision,
                    scope="transaction.manual_edit",
                ),
                _manual(transactions[0]["entity_id"]),
            )
        else:

            def add_party(context):
                party_id = new_entity_id()
                context.add_party(PartyRecord(party_id))
                return MutationOutcome(result={"party_id": party_id})

            edited = session.execute(
                _request(generation, "restored-party", receipt.snapshot_revision),
                add_party,
            )
        assert edited.committed_revision == receipt.snapshot_revision + 1
        assert session.read_snapshot(lambda reader: reader.info.dataset_revision) == (
            edited.committed_revision
        )
        second = session.backup(tmp_path / "rebackup")
        assert second.dataset_revision == edited.committed_revision
    restored = restore_workspace(tmp_path / "rebackup", tmp_path / "second-workspace")
    with InactiveRestoreSession(restored) as session:
        assert (
            session.read_snapshot(lambda reader: reader.info.dataset_revision)
            == second.dataset_revision
        )
    assert not (tmp_path / "data").exists()
    assert data_bytes


def test_wrong_provider_and_independent_hash_rejected(tmp_path: Path) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    wrong = replace(
        expected.activation_evidence,
        installed_release_artifact_sha256="1" * 64,
    )
    flipped = module.RecoveryCaptureInput(
        source.data_dir,
        tmp_path / "rejected",
        _FlipProvider(expected.activation_evidence, wrong),
        source.release_paths,
        source.migration_candidate,
    )
    with pytest.raises(BackupVerificationError, match="^Local recovery graph proof"):
        module.capture_recovery_bundle(flipped, expected)
    assert not (tmp_path / "rejected").exists()
    other = replace(expected, activation_sha256="0" * 64)
    with pytest.raises(BackupVerificationError):
        module.capture_recovery_bundle(
            module.RecoveryCaptureInput(
                source.data_dir,
                tmp_path / "hash",
                source.evidence_provider,
                source.release_paths,
                source.migration_candidate,
            ),
            other,
        )


def test_pointer_change_during_publication_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, paths, _generation, _tx, _account = _live(tmp_path)
    original = module.fsync_attempt_tree

    def mutate(path: Path) -> None:
        payload = json.loads(paths.activation.read_text())
        payload["release_artifact_sha256"] = "2" * 64
        paths.activation.write_bytes(json.dumps(payload).encode())
        original(path)

    monkeypatch.setattr(module, "fsync_attempt_tree", mutate)
    original_db = next(paths.generations_root.iterdir())
    database = original_db / "finjuice.sqlite3"
    before = database.read_bytes()
    with pytest.raises(BackupVerificationError) as error:
        module.capture_recovery_bundle(source, expected)
    assert "PRIVATE" not in str(error.value)
    assert not source.destination.exists()
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "defect", ["provider", "mixed-release", "mixed-snapshot", "missing", "tamper"]
)
def test_verify_rejects_mixed_or_damaged_graph(tmp_path: Path, defect: str) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    receipt = module.capture_recovery_bundle(source, expected)
    bundle = source.destination
    if defect == "provider":
        with pytest.raises(BackupVerificationError):
            module.verify_recovery_bundle(bundle, replace(expected, activation_sha256="0" * 64))
        return
    if defect == "mixed-release":
        (bundle / "release" / expected.wheel_basename).write_bytes(_wheel(version="9.9.9"))
    elif defect == "mixed-snapshot":
        other = tmp_path / "other-gen"
        generation = new_entity_id()
        with RepositoryBuilder(GenerationPaths(other), generation) as builder:
            builder.finalize()
        shutil.rmtree(bundle / "snapshot")
        create_backup(other / "finjuice.sqlite3", bundle / "snapshot")
    elif defect == "missing":
        (bundle / "activation" / "active.json").unlink()
    else:
        target = next((bundle / "capsule" / "candidate" / "objects" / "sha256").glob("*/*"))
        target.chmod(0o600)
        target.write_bytes(b"PRIVATE_CHANGED")
    with pytest.raises(BackupVerificationError) as error:
        module.verify_recovery_bundle(bundle, expected)
    assert "PRIVATE" not in str(error.value)
    assert receipt.kind == "local_graph_verified"


@pytest.mark.parametrize("defect", ["extra", "symlink", "fifo"])
def test_unknown_and_special_entries_fail(tmp_path: Path, defect: str) -> None:
    source, expected, _paths, _generation, _tx, _account = _live(tmp_path)
    module.capture_recovery_bundle(source, expected)
    bundle = source.destination
    if defect == "extra":
        (bundle / "PRIVATE_EXTRA").write_bytes(b"x")
    elif defect == "symlink":
        (bundle / "PRIVATE_LINK").symlink_to(bundle / "activation" / "active.json")
    else:
        os.mkfifo(bundle / "PRIVATE_FIFO")
    with pytest.raises(BackupVerificationError) as error:
        module.verify_recovery_bundle(bundle, expected)
    assert "PRIVATE" not in str(error.value)


def test_overlap_existing_and_publication_race_preserve_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, paths, generation, _tx, _account = _live(tmp_path)
    original_db = paths.generation(generation).database.read_bytes()
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "sentinel").write_bytes(b"old")
    overlapping = module.RecoveryCaptureInput(
        source.data_dir,
        source.data_dir / "nested-bundle",
        source.evidence_provider,
        source.release_paths,
        source.migration_candidate,
    )
    for destination in (existing, overlapping.destination, source.migration_candidate):
        with pytest.raises(BackupVerificationError):
            module.capture_recovery_bundle(
                module.RecoveryCaptureInput(
                    source.data_dir,
                    destination,
                    source.evidence_provider,
                    source.release_paths,
                    source.migration_candidate,
                ),
                expected,
            )
    assert (existing / "sentinel").read_bytes() == b"old"
    raced = tmp_path / "raced"
    original = module.rename_exclusive

    def race(src: Path, target: Path) -> None:
        target.mkdir()
        (target / "sentinel").write_bytes(b"competitor")
        original(src, target)

    monkeypatch.setattr(module, "rename_exclusive", race)
    with pytest.raises(BackupVerificationError):
        module.capture_recovery_bundle(
            module.RecoveryCaptureInput(
                source.data_dir,
                raced,
                source.evidence_provider,
                source.release_paths,
                source.migration_candidate,
            ),
            expected,
        )
    assert (raced / "sentinel").read_bytes() == b"competitor"
    assert not (raced / "recovery-graph.json").exists()
    assert paths.generation(generation).database.read_bytes() == original_db


def test_fsync_failure_has_no_success_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, paths, generation, _tx, _account = _live(tmp_path)
    original = paths.generation(generation).database.read_bytes()
    sentinel = tmp_path / "previous"
    sentinel.write_bytes(b"preserved")

    def fail(_path: Path) -> None:
        raise OSError("PRIVATE_FSYNC")

    monkeypatch.setattr(module, "fsync_attempt_tree", fail)
    with pytest.raises(BackupVerificationError) as error:
        module.capture_recovery_bundle(source, expected)
    assert str(error.value) == module._ERROR
    assert "PRIVATE" not in str(error.value)
    assert not source.destination.exists()
    assert paths.generation(generation).database.read_bytes() == original
    assert sentinel.read_bytes() == b"preserved"


@pytest.mark.parametrize("phase", ["_materialize", "_seal"])
def test_failed_capture_cleans_its_owned_temporary_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    source, expected, *_ = _live(tmp_path)

    def fail(*args):
        raise OSError("synthetic failure")

    monkeypatch.setattr(module, phase, fail)
    with pytest.raises(BackupVerificationError):
        module.capture_recovery_bundle(source, expected)
    assert not list(tmp_path.glob(".recovery-graph-*"))
    assert not list(tmp_path.glob(".recovery-scratch-*"))


@pytest.mark.parametrize("field", ["size", "activation_revision"])
def test_manifest_keeps_numeric_types(tmp_path: Path, field: str) -> None:
    source, expected, *_ = _live(tmp_path)
    module.capture_recovery_bundle(source, expected)
    path = source.destination / "recovery-graph.json"
    payload = json.loads(path.read_bytes())
    if field == "size":
        payload["files"][0]["size"] = float(payload["files"][0]["size"])
    else:
        payload["activation"]["dataset_revision"] = float(payload["activation"]["dataset_revision"])
    body = {key: value for key, value in payload.items() if key != "graph_digest"}
    payload["graph_digest"] = module._sha(module._canonical(body))
    path.write_bytes(module._canonical(payload))
    with pytest.raises(BackupVerificationError):
        module.verify_recovery_bundle(source.destination, expected)


def test_failure_cleanup_preserves_replaced_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, *_ = _live(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "sentinel"
    sentinel.write_bytes(b"retained")

    def replace_staging(staging, *args):
        staging.rename(tmp_path / "detached-owned-staging")
        staging.symlink_to(foreign, target_is_directory=True)
        raise OSError("synthetic failure")

    monkeypatch.setattr(module, "_materialize", replace_staging)
    with pytest.raises(BackupVerificationError) as error:
        module.capture_recovery_bundle(source, expected)
    assert str(error.value) == module._ERROR
    assert sentinel.read_bytes() == b"retained"


def test_final_parent_fsync_failure_does_not_return_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, paths, generation, *_ = _live(tmp_path)
    raw = paths.activation.read_bytes()
    original = paths.generation(generation).database.read_bytes()

    def fail(path):
        raise OSError("synthetic late durability failure")

    monkeypatch.setattr(module, "_fsync_directory", fail)
    with pytest.raises(BackupVerificationError):
        module.capture_recovery_bundle(source, expected)
    assert source.destination.is_dir()
    assert paths.activation.read_bytes() == raw
    assert paths.generation(generation).database.read_bytes() == original
    assert not list(tmp_path.glob(".recovery-scratch-*"))


@pytest.mark.parametrize("role", ["activation", "release"])
def test_unknown_empty_role_directory_is_rejected(tmp_path: Path, role: str) -> None:
    source, expected, *_ = _live(tmp_path)
    module.capture_recovery_bundle(source, expected)
    (source.destination / role / "unexpected" / "empty").mkdir(parents=True)

    with pytest.raises(BackupVerificationError):
        module.verify_recovery_bundle(source.destination, expected)


def test_snapshot_verification_binds_the_restored_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.storage.sqlite.backup import create_backup

    source, expected, paths, generation, *_ = _live(tmp_path)
    module.capture_recovery_bundle(source, expected)
    alternate = tmp_path / "alternate"
    create_backup(paths.generation(generation).database, alternate)
    real_restore = module.restore_backup

    def restore_alternative(_backup: Path, target: Path):
        return real_restore(alternate, target)

    monkeypatch.setattr(module, "restore_backup", restore_alternative)
    with pytest.raises(BackupVerificationError):
        module.verify_recovery_bundle(source.destination, expected)
