"""Synthetic tests for immutable source-object publication."""

from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from finjuice.pipeline.storage.sqlite import GenerationPaths, SourceObjectStore
from finjuice.pipeline.storage.sqlite import objects as object_module
from finjuice.pipeline.storage.sqlite.errors import (
    ObjectCorruptionError,
    ObjectStoreError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.objects import _is_link_or_reparse_point


def test_windows_reparse_point_is_treated_as_redirecting_path() -> None:
    entry = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )

    assert _is_link_or_reparse_point(entry)


def test_object_store_publishes_read_only_content_and_reuses_by_digest(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    store = SourceObjectStore(paths)

    first = store.publish(io.BytesIO(b"synthetic financial source\n"))
    second = store.publish(io.BytesIO(b"synthetic financial source\n"))

    assert first.artifact_id == second.artifact_id
    assert first.reused is False
    assert second.reused is True
    target = paths.root / first.relative_path
    assert target.read_bytes() == b"synthetic financial source\n"
    assert target.stat().st_mode & 0o222 == 0
    assert store.verify(first.artifact_id, first.byte_length).digest_hex == first.digest_hex


def test_object_store_syncs_read_only_mode_after_applying_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "mode-before-sync")
    events: list[str] = []
    real_fchmod = object_module.os.fchmod
    real_fsync = object_module.os.fsync

    def record_fchmod(file_descriptor: int, mode: int) -> None:
        events.append("fchmod")
        real_fchmod(file_descriptor, mode)

    def record_fsync(file_descriptor: int) -> None:
        if stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            events.append("file-fsync")
        real_fsync(file_descriptor)

    monkeypatch.setattr(object_module.os, "fchmod", record_fchmod)
    monkeypatch.setattr(object_module.os, "fsync", record_fsync)

    SourceObjectStore(paths).publish(io.BytesIO(b"mode and bytes"))

    assert events[:2] == ["fchmod", "file-fsync"]


def test_object_store_rejects_mutable_or_corrupted_existing_object(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    store = SourceObjectStore(paths)
    artifact = store.publish(io.BytesIO(b"original"))
    target = paths.root / artifact.relative_path
    target.chmod(0o644)

    with pytest.raises(ObjectCorruptionError, match="write permission"):
        store.verify(artifact.artifact_id)

    target.write_bytes(b"changed!")
    target.chmod(0o444)
    with pytest.raises(ObjectCorruptionError, match="identity"):
        store.verify(artifact.artifact_id)


def test_object_store_rejects_symlinked_digest_prefix_and_cleans_staging(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    store = SourceObjectStore(paths)
    store.prepare()
    content = b"prefix attack"
    prefix = hashlib.sha256(content).hexdigest()[:2]
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, paths.sha256_objects / prefix)

    with pytest.raises(RepositoryPathError, match="symlink|real directory"):
        store.publish(io.BytesIO(content))

    assert list(paths.sha256_objects.glob(".object-*.tmp")) == []
    assert list(outside.iterdir()) == []


def test_object_store_rejects_symlink_generation_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias = tmp_path / "alias"
    os.symlink(real_root, alias)

    with pytest.raises(RepositoryPathError, match="symlink|real directory"):
        SourceObjectStore(GenerationPaths(alias)).prepare()


@pytest.mark.parametrize("directory_name", ["root", "objects", "sha256"])
def test_object_store_rejects_permissive_existing_namespace(
    tmp_path: Path,
    directory_name: str,
) -> None:
    paths = GenerationPaths(tmp_path / f"permissive-{directory_name}")
    paths.root.mkdir(mode=0o700)
    if directory_name in {"objects", "sha256"}:
        paths.objects.mkdir(mode=0o700)
    if directory_name == "sha256":
        paths.sha256_objects.mkdir(mode=0o700)
    target = {
        "root": paths.root,
        "objects": paths.objects,
        "sha256": paths.sha256_objects,
    }[directory_name]
    target.chmod(0o755)

    with pytest.raises(RepositoryPathError, match="must be private"):
        SourceObjectStore(paths).prepare()


def test_object_store_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "source.fifo"
    os.mkfifo(fifo)

    with pytest.raises(ObjectStoreError, match="regular file"):
        SourceObjectStore(GenerationPaths(tmp_path / "generation")).publish_path(fifo)


def test_new_object_directories_and_link_are_synced_in_durable_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "durable-generation")
    store = SourceObjectStore(paths)
    content = b"durable object"
    digest = hashlib.sha256(content).hexdigest()
    target_parent = paths.sha256_objects / digest[:2]
    synced: list[Path] = []
    real_fsync_directory = object_module._fsync_directory

    def record_fsync(path: Path) -> None:
        synced.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(object_module, "_fsync_directory", record_fsync)

    artifact = store.publish(io.BytesIO(content))

    assert synced == [
        tmp_path,
        paths.root,
        paths.objects,
        paths.sha256_objects,
        target_parent,
        target_parent,
    ]
    assert (paths.root / artifact.relative_path).read_bytes() == content


def test_object_publication_syncs_link_before_removing_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "object-order")
    store = SourceObjectStore(paths)
    content = b"ordered publication"
    digest = hashlib.sha256(content).hexdigest()
    store.prepare()
    (paths.sha256_objects / digest[:2]).mkdir(mode=0o700)
    states: list[tuple[int, bool]] = []
    real_fsync_directory = object_module._fsync_directory

    def record_fsync(path: Path) -> None:
        states.append((len(list(paths.sha256_objects.glob(".object-*.tmp"))), path.exists()))
        real_fsync_directory(path)

    monkeypatch.setattr(object_module, "_fsync_directory", record_fsync)

    store.publish(io.BytesIO(content))

    assert states == [(1, True), (0, True)]


def test_object_publication_reports_directory_sync_failure_and_rolls_back_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "object-sync-failure")
    store = SourceObjectStore(paths)
    content = b"failed publication"
    digest = hashlib.sha256(content).hexdigest()
    store.prepare()
    target = paths.object_path(digest)
    target.parent.mkdir(mode=0o700)

    def fail_fsync(path: Path) -> None:
        raise OSError(f"injected sync failure for {path}")

    monkeypatch.setattr(object_module, "_fsync_directory", fail_fsync)

    with pytest.raises(ObjectStoreError, match="published durably"):
        store.publish(io.BytesIO(content))

    assert not target.exists()
    assert list(paths.sha256_objects.glob(".object-*.tmp")) == []


def test_new_prefix_directory_sync_failure_does_not_publish_an_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "prefix-sync-failure")
    store = SourceObjectStore(paths)
    content = b"prefix failure"
    digest = hashlib.sha256(content).hexdigest()
    real_fsync_directory = object_module._fsync_directory

    def fail_prefix_parent_sync(path: Path) -> None:
        if path == paths.sha256_objects:
            raise OSError("injected prefix parent sync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(object_module, "_fsync_directory", fail_prefix_parent_sync)

    with pytest.raises(RepositoryPathError, match="could not be created"):
        store.publish(io.BytesIO(content))

    assert not paths.object_path(digest).exists()
    assert list(paths.sha256_objects.glob(".object-*.tmp")) == []
