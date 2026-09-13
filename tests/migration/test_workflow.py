"""Synthetic frozen-capture migration publication and parity tests."""

from __future__ import annotations

import errno
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from finjuice.pipeline.backup import (
    BackupError,
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
)
from finjuice.pipeline.backup import io as backup_io
from finjuice.pipeline.migration import (
    MigrationError,
    build_migration,
    plan_migration,
    verify_migration,
)
from finjuice.pipeline.migration import build as workflow
from finjuice.pipeline.migration import verify as verification
from finjuice.pipeline.migration.common import MARKER, tree_inventory
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader


@pytest.fixture
def capture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "live"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"synthetic\x00\xff")
    (source / "empty").mkdir()
    backup = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source=source,
            output=backup,
            consistency=ConsistencyEvidence("stopped_writers", ("synthetic-test",)),
            extra_roots=(SourceRoot("optional", "optional", None),),
        )
    )
    plan = tmp_path / "plan.json"
    plan_migration(backup / "backup-manifest.json", output=plan, active_data_dir=source)
    return source, backup, plan


def test_build_verify_and_retry_preserve_source(capture: tuple[Path, Path, Path], tmp_path: Path):
    source, backup, plan = capture
    original = tree_inventory(source), tree_inventory(backup)
    target = tmp_path / "candidate"
    result = build_migration(plan, target, active_data_dir=source).to_dict()
    assert result["status"] == "ok"
    assert result["cutover_ready"] is False
    assert (
        build_migration(plan, target, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    second = tmp_path / "second"
    build_migration(plan, second, active_data_dir=source)
    assert semantic_snapshot(target / "finjuice.sqlite3") == semantic_snapshot(
        second / "finjuice.sqlite3"
    )
    assert original == (tree_inventory(source), tree_inventory(backup))
    with RepositoryReader(target / "finjuice.sqlite3") as reader:
        revisions = reader.rows("config_revisions")
        assert len(revisions) == 1
        assert (
            json.loads(revisions[0]["canonical_payload_json"])["origin_kind"]
            == "legacy_current_state"
        )
        assert reader.rows("audit_events") == []
        assert reader.info.dataset_revision == 0


@pytest.mark.parametrize("change", ["modify", "add", "delete", "outside_payload"])
def test_changed_capture_rejected(capture: tuple[Path, Path, Path], tmp_path: Path, change: str):
    source, backup, plan = capture
    frozen = backup / "payload" / "data" / "opaque.bin"
    if change == "modify":
        frozen.write_bytes(b"changed")
    elif change == "add":
        (frozen.parent / "extra").write_text("new")
    elif change == "delete":
        frozen.unlink()
    else:
        (backup / "extra").write_text("new")
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, tmp_path / "candidate", active_data_dir=source)
    assert not (tmp_path / "candidate").exists()


def test_nonempty_and_active_target_rejected(capture: tuple[Path, Path, Path], tmp_path: Path):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "sentinel").write_text("keep")
    for path in (target, source, source / "child"):
        with pytest.raises((BackupError, MigrationError)):
            build_migration(plan, path, active_data_dir=source)
    assert (target / "sentinel").read_text() == "keep"


def test_failed_attempt_is_not_published(capture, tmp_path, monkeypatch):
    source, _backup, plan = capture
    real = workflow.populate_repository

    def broken(root, manifest, paths, **kwargs):
        real(root, manifest, paths, **kwargs)
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(workflow, "populate_repository", broken)
    target = tmp_path / "candidate"
    with pytest.raises(OSError, match="synthetic disk failure"):
        build_migration(plan, target, active_data_dir=source)
    assert not target.exists()
    attempts = list(tmp_path.glob(".migration-attempt-*"))
    assert len(attempts) == 1
    assert not (attempts[0] / MARKER).exists()
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, attempts[0], active_data_dir=source)


@pytest.mark.parametrize("tamper", ["marker", "database", "source_object"])
def test_candidate_tamper_rejected(capture, tmp_path, tamper):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    if tamper == "marker":
        (target / MARKER).unlink()
    elif tamper == "database":
        with sqlite3.connect(target / "finjuice.sqlite3") as connection:
            connection.execute("UPDATE repository_meta SET dataset_revision=1")
    else:
        object_path = next((target / "objects" / "sha256").glob("*/*"))
        object_path.chmod(0o600)
        object_path.write_bytes(b"tampered")
    with pytest.raises((ValueError, BackupError, RuntimeError)):
        verify_migration(target)


def test_source_change_during_build_prevents_publication(capture, tmp_path, monkeypatch):
    source, backup, plan = capture
    real = workflow.populate_repository

    def changed(root, manifest, paths, **kwargs):
        real(root, manifest, paths, **kwargs)
        if root == backup:
            (backup / "payload" / "data" / "added").write_text("race")

    monkeypatch.setattr(workflow, "populate_repository", changed)
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, tmp_path / "candidate", active_data_dir=source)
    assert not (tmp_path / "candidate").exists()


def test_empty_target_and_missing_marker_retry(capture, tmp_path):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    target.mkdir()
    build_migration(plan, target, active_data_dir=source)
    (target / MARKER).unlink()
    with pytest.raises(MigrationError, match="completion marker"):
        build_migration(plan, target, active_data_dir=source)


def test_plan_is_immutable_and_requires_completed_capture(capture, tmp_path):
    source, backup, plan = capture
    before = plan.read_bytes()
    with pytest.raises(BackupError):
        plan_migration(backup, output=plan, active_data_dir=source)
    assert plan.read_bytes() == before
    (backup / "FINJUICE_BACKUP_COMPLETE").unlink()
    with pytest.raises(BackupError):
        plan_migration(backup, output=tmp_path / "another-plan", active_data_dir=source)


def test_rehashed_database_tamper_fails_source_parity(capture, tmp_path):
    from finjuice.pipeline.migration.common import canonical, file_digest, seal

    source, _backup, plan = capture
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    with sqlite3.connect(target / "finjuice.sqlite3") as connection:
        connection.execute("UPDATE repository_meta SET dataset_revision=1")
    location = target / "manifests" / "migration-manifest.json"
    manifest = json.loads(location.read_text())
    manifest.pop("canonical_digest")
    manifest["database_digest"] = file_digest(target / "finjuice.sqlite3")
    manifest["semantic_digest"] = semantic_snapshot(target / "finjuice.sqlite3")
    manifest = seal(manifest)
    location.write_text(canonical(manifest))
    (target / MARKER).write_text(manifest["canonical_digest"] + "\n")
    with pytest.raises(MigrationError, match="differ from source"):
        verify_migration(target)


@pytest.mark.parametrize("stage", ["capture_copy", "repository_replay"])
@pytest.mark.parametrize(
    "error", [OSError(errno.ENOSPC, "synthetic full"), RuntimeError("synthetic")]
)
def test_verify_failure_cleans_scratch_and_preserves_evidence(
    capture, tmp_path, monkeypatch, stage, error
):
    source, backup, plan = capture
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    original = tuple(tree_inventory(path) for path in (source, backup, target))
    plan_bytes = plan.read_bytes()
    scratch_parent = tmp_path / "scratch"
    scratch_parent.mkdir()
    allocated = []
    real_temporary = verification.tempfile.TemporaryDirectory
    real_populate = workflow.populate_repository

    @contextmanager
    def temporary(**kwargs):
        with real_temporary(dir=scratch_parent, **kwargs) as directory:
            allocated.append(Path(directory))
            yield directory

    def broken_copy(_source, destination):
        destination.write_bytes(b"partial synthetic copy")
        raise error

    def broken_replay(root, manifest, paths, **kwargs):
        real_populate(root, manifest, paths, **kwargs)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(verification, "tempfile", SimpleNamespace(TemporaryDirectory=temporary))
        if stage == "capture_copy":
            patch.setattr(verification, "shutil", SimpleNamespace(copyfile=broken_copy))
        else:
            patch.setattr(workflow, "populate_repository", broken_replay)
        with pytest.raises(type(error)) as raised:
            verify_migration(target)
        assert raised.value is error

    assert len(allocated) == 1
    assert not allocated[0].exists()
    assert list(scratch_parent.iterdir()) == []
    assert tuple(tree_inventory(path) for path in (source, backup, target)) == original
    assert plan.read_bytes() == plan_bytes
    assert verify_migration(target).to_dict()["status"] == "ok"


@pytest.mark.parametrize("empty_target", [False, True])
@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EIO])
def test_publish_failure_cleans_attempt_and_keeps_originals(
    capture, tmp_path, monkeypatch, empty_target, error_number
):
    source, backup, plan = capture
    target = tmp_path / "candidate"
    if empty_target:
        target.mkdir()
    original = tuple(tree_inventory(path) for path in (source, backup))
    target_stat = target.stat() if empty_target else None
    plan_bytes = plan.read_bytes()
    real_rename = backup_io.os.rename

    def broken_rename(staging, output):
        if Path(staging).name.startswith(".migration-attempt-"):
            raise OSError(error_number, "synthetic publication failure")
        return real_rename(staging, output)

    with monkeypatch.context() as patch:
        patch.setattr(backup_io, "rename_exclusive", broken_rename)
        patch.setattr(backup_io.os, "rename", broken_rename)
        with pytest.raises(BackupError, match="Disk is full|Backup I/O failed"):
            build_migration(plan, target, active_data_dir=source)

    assert list(tmp_path.glob(".migration-attempt-*")) == []
    assert target.exists() is empty_target
    if empty_target:
        assert list(target.iterdir()) == []
        current = target.stat()
        for field in ("st_dev", "st_ino", "st_mode", "st_mtime_ns"):
            assert getattr(current, field) == getattr(target_stat, field)
    assert tuple(tree_inventory(path) for path in (source, backup)) == original
    assert plan.read_bytes() == plan_bytes
    with pytest.raises(MigrationError, match="already used"):
        build_migration(plan, target, active_data_dir=source)
    parent = next((tmp_path / ".finjuice-migration-attempts").iterdir()).name
    retry = build_migration(
        plan, tmp_path / "retry", active_data_dir=source, parent_attempt_id=parent
    )
    assert retry.to_dict()["status"] == "ok"
    assert tuple(tree_inventory(path) for path in (source, backup)) == original


def test_post_publication_sync_failure_can_verify_and_retry(capture, tmp_path, monkeypatch):
    source, backup, plan = capture
    target = tmp_path / "candidate"
    original = tuple(tree_inventory(path) for path in (source, backup))
    real_sync = backup_io.fsync_parent_chain

    def broken_sync(parent):
        if target.exists():
            raise OSError(errno.ENOSPC, "synthetic parent sync failure")
        return real_sync(parent)

    with monkeypatch.context() as patch:
        patch.setattr(backup_io, "fsync_parent_chain", broken_sync)
        with pytest.raises(OSError, match="synthetic parent sync failure"):
            build_migration(plan, target, active_data_dir=source)

    verified = verify_migration(target).to_dict()
    retry = build_migration(plan, target, active_data_dir=source).to_dict()
    assert retry["status"] == "already_complete"
    assert retry["manifest_digest"] == verified["manifest_digest"]
    assert list(tmp_path.glob(".migration-attempt-*")) == []
    assert tuple(tree_inventory(path) for path in (source, backup)) == original
