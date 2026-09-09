"""Synthetic tests for immutable source-object publication."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import GenerationPaths, SourceObjectStore
from finjuice.pipeline.storage.sqlite.errors import (
    ObjectCorruptionError,
    ObjectStoreError,
    RepositoryPathError,
)


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


def test_object_store_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "source.fifo"
    os.mkfifo(fifo)

    with pytest.raises(ObjectStoreError, match="regular file"):
        SourceObjectStore(GenerationPaths(tmp_path / "generation")).publish_path(fifo)
