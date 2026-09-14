from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import backup_publication as publication
from finjuice.pipeline.storage.sqlite.errors import BackupTransferError, RepositoryPathError


def _container(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    return publication.prepare_container(tmp_path / "backup", source), source


def _staged_manifest(workspace: publication.AttemptWorkspace, content: bytes = b"manifest") -> Path:
    manifest = workspace.staging_root / publication.MANIFEST_FILENAME
    seed = hashlib.sha256(content).hexdigest()
    backup_id = seed[:32]
    body = {
        "backup_id": backup_id,
        "created_at": "2026-09-14T00:00:00+00:00",
        "dataset_revision": 0,
        "files": [
            {
                "byte_length": 0,
                "path": "finjuice.sqlite3",
                "sha256": "sha256:" + ("0" * 64),
            }
        ],
        "kind": "finjuice.sqlite.generation-backup",
        "schema_version": 1,
        "source_generation": "00000000-0000-0000-0000-000000000000",
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    document = {**body, "manifest_digest": "sha256:" + hashlib.sha256(canonical).hexdigest()}
    manifest.write_bytes(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
    return manifest


def _manifest_digest(manifest: Path) -> str:
    return json.loads(manifest.read_text())["manifest_digest"]


def _publish_one(tmp_path: Path, content: bytes = b"manifest") -> tuple[Path, Path, Path]:
    container, _source = _container(tmp_path)
    workspace = publication.begin_attempt(container)
    manifest = _staged_manifest(workspace, content)
    published = publication.publish_attempt(workspace)
    digest = _manifest_digest(published / publication.MANIFEST_FILENAME)
    publication.publish_current_pointer(
        container,
        published,
        published / publication.MANIFEST_FILENAME,
        digest,
    )
    return container, published, manifest


def test_attempt_publication_writes_exact_pointer_and_preserves_attempt(
    tmp_path: Path,
) -> None:
    container = tmp_path / "container"
    source = container.parent / "source"
    source.mkdir(parents=True)
    container = publication.prepare_container(container, source)
    workspace = publication.begin_attempt(container)
    content = b'{"safe":true}'
    _staged_manifest(workspace, content)

    published = publication.publish_attempt(workspace)
    digest = _manifest_digest(published / publication.MANIFEST_FILENAME)
    publication.publish_current_pointer(
        container,
        published,
        published / publication.MANIFEST_FILENAME,
        digest,
    )

    pointer = json.loads((container / publication.CURRENT_POINTER_FILENAME).read_text())
    assert set(pointer) == {
        "pointer_schema_version",
        "attempt_id",
        "manifest_path",
        "manifest_digest",
    }
    assert pointer == {
        "pointer_schema_version": 1,
        "attempt_id": workspace.attempt_id,
        "manifest_path": f"attempts/{workspace.attempt_id}/backup-manifest.json",
        "manifest_digest": digest,
    }
    assert (
        json.loads((published / publication.MANIFEST_FILENAME).read_text())["manifest_digest"]
        == digest
    )


def test_prepare_rejects_legacy_direct_manifest_without_touching_it(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "backup"
    destination.mkdir(mode=0o700)
    legacy = destination / publication.MANIFEST_FILENAME
    legacy.write_bytes(b"legacy")

    with pytest.raises(RepositoryPathError, match="legacy_layout_requires_rebackup") as raised:
        publication.prepare_container(destination, source)

    assert getattr(raised.value, "reason") == "legacy_layout_requires_rebackup"
    assert legacy.read_bytes() == b"legacy"


def test_container_rejects_unrelated_top_level_entry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "backup"
    destination.mkdir(mode=0o700)
    (destination / "unrelated").write_bytes(b"x")

    with pytest.raises(RepositoryPathError):
        publication.prepare_container(destination, source)


def test_source_and_destination_symlink_ancestors_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_alias = tmp_path / "source-alias"
    destination = tmp_path / "backup"
    destination_alias = tmp_path / "backup-alias"
    source_alias.symlink_to(source, target_is_directory=True)
    destination_alias.symlink_to(destination, target_is_directory=True)

    with pytest.raises(RepositoryPathError):
        publication.prepare_container(destination, source_alias)
    with pytest.raises(RepositoryPathError):
        publication.prepare_container(destination_alias, source)


def test_publish_failure_after_rename_retains_new_attempt_and_old_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, old_attempt, _manifest = _publish_one(tmp_path, b"old")
    old_pointer = (container / publication.CURRENT_POINTER_FILENAME).read_bytes()
    workspace = publication.begin_attempt(container)
    _staged_manifest(workspace, b"new")

    real_fsync_directory = publication._fsync_directory

    def fail_attempt_parent(path: Path) -> None:
        if path == workspace.attempts_root:
            raise OSError("injected directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(publication, "_fsync_directory", fail_attempt_parent)
    with pytest.raises(BackupTransferError):
        publication.publish_attempt(workspace)

    assert old_attempt.is_dir()
    assert (container / publication.CURRENT_POINTER_FILENAME).read_bytes() == old_pointer
    assert (workspace.attempts_root / workspace.attempt_id).is_dir()


def test_pointer_fsync_failure_retains_published_attempt_and_does_not_claim_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, old_attempt, _manifest = _publish_one(tmp_path, b"old")
    old_pointer = (container / publication.CURRENT_POINTER_FILENAME).read_bytes()
    workspace = publication.begin_attempt(container)
    content = b"new"
    _staged_manifest(workspace, content)
    published = publication.publish_attempt(workspace)
    digest = _manifest_digest(published / publication.MANIFEST_FILENAME)

    real_fsync_directory = publication._fsync_directory

    def fail_container_fsync(path: Path) -> None:
        if path == container:
            raise OSError("injected pointer directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(publication, "_fsync_directory", fail_container_fsync)
    with pytest.raises(BackupTransferError):
        publication.publish_current_pointer(
            container,
            published,
            published / publication.MANIFEST_FILENAME,
            digest,
        )

    assert old_attempt.is_dir()
    assert published.is_dir()
    assert (container / publication.CURRENT_POINTER_FILENAME).read_bytes() != old_pointer


def test_pointer_write_all_handles_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, _old_attempt, _manifest = _publish_one(tmp_path, b"old")
    workspace = publication.begin_attempt(container)
    content = b"new"
    _staged_manifest(workspace, content)
    published = publication.publish_attempt(workspace)
    digest = _manifest_digest(published / publication.MANIFEST_FILENAME)
    real_write = publication.os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[:1])

    monkeypatch.setattr(publication.os, "write", short_write)
    publication.publish_current_pointer(
        container,
        published,
        published / publication.MANIFEST_FILENAME,
        digest,
    )
    assert (
        json.loads((container / publication.CURRENT_POINTER_FILENAME).read_text())["attempt_id"]
        == workspace.attempt_id
    )


def test_pointer_no_progress_fails_and_removes_owned_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _old_attempt, _manifest = _publish_one(tmp_path, b"old")
    old_pointer = (container / publication.CURRENT_POINTER_FILENAME).read_bytes()
    workspace = publication.begin_attempt(container)
    content = b"new"
    _staged_manifest(workspace, content)
    published = publication.publish_attempt(workspace)

    monkeypatch.setattr(publication.os, "write", lambda _fd, _data: 0)
    with pytest.raises(BackupTransferError):
        publication.publish_current_pointer(
            container,
            published,
            published / publication.MANIFEST_FILENAME,
            _manifest_digest(published / publication.MANIFEST_FILENAME),
        )
    assert (container / publication.CURRENT_POINTER_FILENAME).read_bytes() == old_pointer
    assert not list(container.glob(f".{publication.CURRENT_POINTER_FILENAME}.*.tmp"))


def test_special_file_in_attempt_is_rejected(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO is unavailable on this platform")
    container, _source = _container(tmp_path)
    workspace = publication.begin_attempt(container)
    os.mkfifo(workspace.staging_root / "special")
    with pytest.raises(BackupTransferError):
        publication.fsync_attempt_tree(workspace.staging_root)


def test_discard_refuses_a_replaced_staging_directory(tmp_path: Path) -> None:
    container, _source = _container(tmp_path)
    workspace = publication.begin_attempt(container)
    workspace.staging_root.rename(tmp_path / "original-staging")
    workspace.staging_root.mkdir(mode=0o700)

    with pytest.raises(BackupTransferError):
        publication.discard_attempt(workspace)
    assert workspace.staging_root.is_dir()


def test_cleanup_child_swap_cannot_follow_link_and_closes_descriptors(tmp_path, monkeypatch):
    container, _source = _container(tmp_path)
    workspace = publication.begin_attempt(container)
    child = workspace.staging_root / "child"
    child.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep"
    sentinel.write_bytes(b"preserve outside data")
    real_open, real_close = os.open, os.close
    opened, closed = [], []

    def swap_before_open(path, flags, *args, **kwargs):
        if path == "child" and kwargs.get("dir_fd") is not None:
            child.rename(workspace.staging_root / "original-child")
            child.symlink_to(outside, target_is_directory=True)
        descriptor = real_open(path, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_close(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", swap_before_open)
        patch.setattr(os, "close", tracked_close)
        with pytest.raises(BackupTransferError):
            publication.discard_attempt(workspace)

    assert sentinel.read_bytes() == b"preserve outside data"
    assert set(opened) == set(closed)
