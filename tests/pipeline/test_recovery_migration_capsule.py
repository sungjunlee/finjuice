"""Independent migration capsule verifies the complete retained source graph."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import ActivationEvidence
from finjuice.pipeline.storage.sqlite import recovery_migration_capsule as module
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from tests.pipeline.test_sqlite_portfolio_reads import _candidate


def _expected(candidate: Path, semantics="canonical_manifest_digest"):
    raw = (candidate / "manifests/migration-manifest.json").read_bytes()
    manifest = json.loads(raw)
    capture_digest = manifest["capture_object_digest"].removeprefix("sha256:")
    capture_raw = (candidate / f"objects/sha256/{capture_digest[:2]}/{capture_digest}").read_bytes()
    capture = json.loads(capture_raw)
    values = (
        [hashlib.sha256(raw).hexdigest(), hashlib.sha256(capture_raw).hexdigest()]
        if semantics == "raw_file_sha256"
        else [
            manifest["canonical_digest"].removeprefix("sha256:"),
            capture["canonical_digest"].removeprefix("sha256:"),
        ]
    )
    return module.ExpectedMigrationCapsule(
        ActivationEvidence("test", "a" * 64, *values), semantics, semantics
    )


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    return _candidate(tmp_path).parent


@pytest.mark.parametrize("semantics", ["canonical_manifest_digest", "raw_file_sha256"])
def test_capsule_survives_original_source_and_candidate_removal(
    candidate: Path, tmp_path: Path, semantics: str
) -> None:
    expected = _expected(candidate, semantics)
    capsule = tmp_path / "capsule"
    receipt = module.capture_migration_capsule(candidate, capsule, expected)
    assert receipt.migration_raw_sha256 != receipt.migration_canonical_digest
    assert receipt.file_count > 4
    shutil.rmtree(candidate)
    shutil.rmtree(tmp_path / "source")
    shutil.rmtree(tmp_path / "capture")
    assert module.verify_migration_capsule(capsule, expected) == receipt
    assert "path" not in repr(receipt)


def test_wrong_digest_semantics_is_not_guessed(candidate: Path, tmp_path: Path) -> None:
    expected = _expected(candidate)
    wrong = module.ExpectedMigrationCapsule(
        expected.activation_evidence, "raw_file_sha256", "raw_file_sha256"
    )
    with pytest.raises(BackupVerificationError):
        module.capture_migration_capsule(candidate, tmp_path / "capsule", wrong)
    assert not (tmp_path / "capsule").exists()


@pytest.mark.parametrize("defect", ["missing", "modified", "extra", "symlink", "fifo", "wal"])
def test_source_defects_fail_without_publishing(
    candidate: Path, tmp_path: Path, defect: str
) -> None:
    expected = _expected(candidate)
    target = next((candidate / "objects/sha256").glob("*/*"))
    if defect == "missing":
        target.unlink()
    elif defect == "modified":
        target.chmod(0o600)
        target.write_bytes(b"PRIVATE_CHANGED")
    elif defect == "extra":
        (candidate / "PRIVATE_EXTRA").write_bytes(b"x")
    elif defect == "symlink":
        (candidate / "PRIVATE_LINK").symlink_to(target)
    elif defect == "fifo":
        os.mkfifo(candidate / "PRIVATE_FIFO")
    else:
        (candidate / "finjuice.sqlite3-wal").write_bytes(b"x")
    with pytest.raises(BackupVerificationError) as error:
        module.capture_migration_capsule(candidate, tmp_path / "capsule", expected)
    assert "PRIVATE" not in str(error.value)
    assert not (tmp_path / "capsule").exists()


def test_existing_overlap_and_dangling_target_preserved(candidate: Path, tmp_path: Path) -> None:
    expected = _expected(candidate)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "sentinel").write_bytes(b"old")
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "missing")
    for destination in (existing, dangling, candidate / "inside", candidate):
        with pytest.raises(BackupVerificationError):
            module.capture_migration_capsule(candidate, destination, expected)
    assert (existing / "sentinel").read_bytes() == b"old"
    assert dangling.is_symlink()


def test_capsule_tamper_and_fsync_failure(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected(candidate)
    failed = tmp_path / "failed"
    original = module.fsync_attempt_tree

    def failure(path):
        raise OSError("PRIVATE_FSYNC")

    monkeypatch.setattr(module, "fsync_attempt_tree", failure)
    with pytest.raises(BackupVerificationError):
        module.capture_migration_capsule(candidate, failed, expected)
    assert not failed.exists()
    monkeypatch.setattr(module, "fsync_attempt_tree", original)
    capsule = tmp_path / "capsule"
    module.capture_migration_capsule(candidate, capsule, expected)
    (capsule / "candidate/finjuice.sqlite3").write_bytes(b"tampered")
    with pytest.raises(BackupVerificationError):
        module.verify_migration_capsule(capsule, expected)


@pytest.mark.parametrize("nonempty", [False, True])
def test_publication_race_does_not_overwrite_destination(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nonempty: bool
) -> None:
    expected = _expected(candidate)
    destination = tmp_path / "capsule"
    original = module.rename_exclusive

    def race(source, target):
        target.mkdir()
        if nonempty:
            (target / "sentinel").write_bytes(b"competitor")
        original(source, target)

    monkeypatch.setattr(module, "rename_exclusive", race)
    with pytest.raises(BackupVerificationError):
        module.capture_migration_capsule(candidate, destination, expected)
    assert destination.is_dir()
    if nonempty:
        assert (destination / "sentinel").read_bytes() == b"competitor"
    else:
        assert list(destination.iterdir()) == []
    assert not (destination / "migration-capsule.json").exists()


def test_known_active_namespace_rejected(candidate: Path, tmp_path: Path) -> None:
    expected = _expected(candidate)
    active = tmp_path / ".finjuice/generations/baseline"
    active.parent.mkdir(parents=True)
    shutil.copytree(candidate, active)
    with pytest.raises(BackupVerificationError):
        module.capture_migration_capsule(active, tmp_path / "capsule", expected)


def test_other_expected_candidate_is_rejected(candidate: Path, tmp_path: Path) -> None:
    expected = _expected(candidate)
    evidence = expected.activation_evidence
    wrong = module.ExpectedMigrationCapsule(
        ActivationEvidence(
            evidence.installed_release_version,
            evidence.installed_release_artifact_sha256,
            "0" * 64,
            evidence.verified_pre_cutover_backup_manifest_sha256,
        ),
        expected.migration_semantics,
        expected.pre_cutover_semantics,
    )
    with pytest.raises(BackupVerificationError):
        module.capture_migration_capsule(candidate, tmp_path / "capsule", wrong)


def test_replaced_staging_cleanup_preserves_foreign_path_and_static_error(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected(candidate)
    foreign = tmp_path / "PRIVATE_FOREIGN"
    foreign.mkdir()
    (foreign / "sentinel").write_bytes(b"retained")

    def replace_staging(path: Path) -> None:
        path.rename(tmp_path / "owned-before-replacement")
        path.symlink_to(foreign, target_is_directory=True)
        raise OSError("PRIVATE_TRIGGER")

    monkeypatch.setattr(module, "fsync_attempt_tree", replace_staging)
    with pytest.raises(BackupVerificationError) as error:
        module.capture_migration_capsule(candidate, tmp_path / "capsule", expected)
    assert str(error.value) == module._ERROR
    assert "PRIVATE" not in str(error.value)
    assert (foreign / "sentinel").read_bytes() == b"retained"
    assert not (tmp_path / "capsule").exists()


def test_source_changes_during_descriptor_copy_fail(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected(candidate)
    source = candidate / "FINJUICE_MIGRATION_COMPLETE"
    identity = source.stat().st_ino
    original = os.read
    changed = False

    def changing_read(fd: int, size: int) -> bytes:
        nonlocal changed
        data = original(fd, size)
        if not changed and os.fstat(fd).st_ino == identity:
            changed = True
            with source.open("ab") as stream:
                stream.write(b"PRIVATE_CHANGED")
        return data

    monkeypatch.setattr(os, "read", changing_read)
    with pytest.raises(BackupVerificationError) as error:
        module.capture_migration_capsule(candidate, tmp_path / "capsule", expected)
    assert changed
    assert str(error.value) == module._ERROR
    assert not (tmp_path / "capsule").exists()


def test_parent_fsync_failure_has_no_success_receipt(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _expected(candidate)
    original = (candidate / "finjuice.sqlite3").read_bytes()
    sentinel = tmp_path / "existing"
    sentinel.write_bytes(b"preserved")
    capsule = tmp_path / "capsule"

    def fail_parent(path: Path) -> None:
        assert capsule.exists()
        raise OSError("PRIVATE_PARENT_FSYNC")

    monkeypatch.setattr(module, "_fsync_directory", fail_parent)
    with pytest.raises(BackupVerificationError) as error:
        module.capture_migration_capsule(candidate, capsule, expected)
    assert str(error.value) == module._ERROR
    assert (candidate / "finjuice.sqlite3").read_bytes() == original
    assert sentinel.read_bytes() == b"preserved"
    assert module.verify_migration_capsule(capsule, expected).capsule_digest


@pytest.mark.parametrize("field", ["file_count", "file_size"])
def test_manifest_numeric_types_are_exact(candidate: Path, tmp_path: Path, field: str) -> None:
    expected = _expected(candidate)
    capsule = tmp_path / "capsule"
    module.capture_migration_capsule(candidate, capsule, expected)
    path = capsule / "migration-capsule.json"
    payload = json.loads(path.read_bytes())
    record = payload["receipt"] if field == "file_count" else payload["files"][0]
    key = "file_count" if field == "file_count" else "size"
    record[key] = float(record[key])
    body = {key: value for key, value in payload.items() if key != "capsule_digest"}
    payload["capsule_digest"] = module._sha(module._canonical(body))
    path.write_bytes(module._canonical(payload))
    with pytest.raises(BackupVerificationError):
        module.verify_migration_capsule(capsule, expected)
