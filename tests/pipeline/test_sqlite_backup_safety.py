"""Backup attempts publish atomically and share strict read/restore verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import backup as backup_module
from finjuice.pipeline.storage.sqlite.backup import (
    DATABASE_BASENAME,
    backup_status,
    create_backup,
    read_backup_manifest,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupTransferError,
    RepositoryBackupError,
    RepositoryPathError,
)
from tests.pipeline.test_sqlite_backup import _build_generation

POINTER = "backup-current.json"


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("boundary", ["_write_manifest", "_publish_staged_database"])
def test_late_failure_with_different_generation_preserves_all_previous_bytes(
    tmp_path, monkeypatch, boundary
):
    first = _build_generation(tmp_path / "first")
    second = _build_generation(tmp_path / "second")
    root = tmp_path / "backup"
    previous = create_backup(first.database, root)
    before = _bytes(root)

    def fail(*args, **kwargs):
        raise OSError("synthetic late failure")

    with monkeypatch.context() as patch:
        patch.setattr(backup_module, boundary, fail)
        with pytest.raises(RepositoryBackupError):
            create_backup(second.database, root)
    for path, content in before.items():
        assert (root / path).read_bytes() == content
    status = backup_status(root)
    assert status.complete and status.manifest.backup_id == previous.backup_id
    assert (
        restore_backup(root, tmp_path / "restored").source_generation == previous.source_generation
    )


def test_repeated_backup_retains_old_attempt_bytes(tmp_path):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    first = create_backup(source.database, root)
    before = _bytes(first.manifest_path.parent)
    second = create_backup(source.database, root)
    assert first.manifest_path != second.manifest_path
    assert _bytes(first.manifest_path.parent) == before
    assert first.database_digest == second.database_digest


def test_directory_fsync_failure_does_not_return_complete_receipt(tmp_path, monkeypatch):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"

    original = os.fsync

    def fail(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory fsync failure")
        return original(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        with pytest.raises(BackupTransferError):
            create_backup(source.database, root)
    assert not backup_status(root).complete
    assert not (root / POINTER).exists()


@pytest.mark.parametrize("progress", [True, False])
def test_partial_write_completes_and_no_progress_write_fails(tmp_path, monkeypatch, progress):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    original = os.write

    def partial(descriptor, data):
        return original(descriptor, data[: max(1, len(data) // 2)]) if progress else 0

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial)
        if progress:
            assert create_backup(source.database, root).complete
        else:
            with pytest.raises(RepositoryBackupError):
                create_backup(source.database, root)
    assert backup_status(root).complete is progress


def test_direct_v1_restore_and_rebackup_keep_data_without_overwriting_v1(tmp_path):
    source = _build_generation(tmp_path / "source")
    created = create_backup(source.database, tmp_path / "container")
    direct = tmp_path / "direct-v1"
    shutil.copytree(created.manifest_path.parent, direct)
    original = _bytes(direct)
    assert read_backup_manifest(direct).backup_id == created.backup_id
    assert backup_status(direct).complete
    with pytest.raises(RepositoryPathError):
        create_backup(source.database, direct)
    assert _bytes(direct) == original
    restored = tmp_path / "restored"
    assert restore_backup(direct, restored).verified
    again = create_backup(restored / DATABASE_BASENAME, tmp_path / "again")
    assert again.source_generation == created.source_generation
    final = tmp_path / "final"
    assert restore_backup(tmp_path / "again", final).verified
    assert (final / DATABASE_BASENAME).read_bytes() == (restored / DATABASE_BASENAME).read_bytes()


@pytest.mark.parametrize("defect", ["missing", "tampered"])
def test_current_pointer_is_required_and_verified(tmp_path, defect):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    create_backup(source.database, root)
    pointer = root / POINTER
    if defect == "missing":
        pointer.unlink()
    else:
        pointer.write_text('{"unexpected": "tampered"}')
    assert not backup_status(root).complete
    with pytest.raises(RepositoryBackupError):
        restore_backup(root, tmp_path / "restore")


@pytest.mark.parametrize("defect", ["symlink", "unknown", "duplicate", "orphan"])
def test_status_and_restore_reject_invalid_direct_payload(tmp_path, defect):
    source = _build_generation(tmp_path / "source")
    created = create_backup(source.database, tmp_path / "container")
    direct = tmp_path / "direct"
    shutil.copytree(created.manifest_path.parent, direct)
    manifest = direct / created.manifest_path.name
    if defect == "symlink":
        database = direct / DATABASE_BASENAME
        database.unlink()
        database.symlink_to(source.database)
    elif defect == "orphan":
        (direct / "orphan").write_bytes(b"unexpected")
    else:
        payload = json.loads(manifest.read_text())
        if defect == "unknown":
            payload["unknown"] = "unexpected"
        else:
            payload["files"].append(payload["files"][-1])
        body = {key: value for key, value in payload.items() if key != "manifest_digest"}
        encoded = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        payload["manifest_digest"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
        manifest.write_text(json.dumps(payload))
    assert not backup_status(direct).complete
    with pytest.raises(RepositoryBackupError):
        restore_backup(direct, tmp_path / "restore")


def test_unexpected_container_file_is_not_pruned(tmp_path):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    create_backup(source.database, root)
    (root / "unexpected").write_bytes(b"keep this")
    before = _bytes(root)
    with pytest.raises(RepositoryPathError):
        create_backup(source.database, root)
    assert _bytes(root) == before


def test_restore_lexical_parent_alias_cannot_overlap_input_container(tmp_path):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    create_backup(source.database, root)
    before = _bytes(root)
    with pytest.raises(RepositoryPathError):
        restore_backup(root, root / "attempts" / "..")
    assert _bytes(root) == before
    assert backup_status(root).complete


def test_create_lexical_parent_alias_cannot_overlap_source(tmp_path):
    source = _build_generation(tmp_path / "source")
    before = _bytes(source.root)
    with pytest.raises(RepositoryPathError):
        create_backup(source.database, source.root / "objects" / "..")
    assert _bytes(source.root) == before


def test_changed_pointer_after_publication_cannot_return_complete(tmp_path, monkeypatch):
    source = _build_generation(tmp_path / "source")
    root = tmp_path / "backup"
    previous = create_backup(source.database, root)
    original = backup_module.publish_current_pointer

    def publish_then_damage(*args, **kwargs):
        original(*args, **kwargs)
        (root / POINTER).write_bytes(b"invalid pointer")

    monkeypatch.setattr(backup_module, "publish_current_pointer", publish_then_damage)
    with pytest.raises(RepositoryBackupError):
        create_backup(source.database, root)
    assert not backup_status(root).complete
    assert backup_status(previous.manifest_path.parent).complete
