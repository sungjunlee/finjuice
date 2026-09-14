"""Synthetic tests for generation backup creation, status, and restore."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder
from finjuice.pipeline.storage.sqlite import backup as backup_module
from finjuice.pipeline.storage.sqlite.backup import (
    DATABASE_BASENAME,
    BackupManifest,
    backup_status,
    create_backup,
    read_backup_manifest,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupTransferError,
    BackupVerificationError,
)


def _build_generation(root: Path) -> GenerationPaths:
    """Publish one minimal synthetic generation and return its paths."""
    paths = GenerationPaths(root)
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        builder.publish_source(io.BytesIO(b"synthetic backup source bytes"))
        builder.finalize()
    return paths


def _digests_by_path(backup_root: Path) -> dict[str, str]:
    """Return the recorded payload digests of one backup, keyed by path."""
    manifest = read_backup_manifest(backup_root)
    return {entry.path: entry.sha256 for entry in manifest.files}


def _object_entry(manifest: BackupManifest) -> str:
    """Return the manifest path of the first backed-up source object."""
    return next(entry.path for entry in manifest.files if entry.role == "object")


def test_create_restore_round_trip_passes_integrity_checks(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)

    # Act
    result = restore_backup(backup_root, tmp_path / "restored")
    status = backup_status(tmp_path / "restored")

    # Assert
    assert created.complete
    assert result.verified
    assert {"integrity_check", "foreign_key_check", "payload_digests"} <= set(result.checks)
    assert result.source_generation == created.source_generation
    assert result.manifest_digest == created.manifest_digest
    assert (tmp_path / "restored" / DATABASE_BASENAME).is_file()
    assert status.complete
    assert status.reason == "complete"


def test_repeated_backup_is_idempotent_for_unchanged_content(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    first = create_backup(generation.database, backup_root)
    first_digests = _digests_by_path(backup_root)

    # Act
    second = create_backup(generation.database, backup_root)

    # Assert
    assert second.database_digest == first.database_digest
    assert _digests_by_path(backup_root) == first_digests
    assert backup_status(backup_root).complete


def test_transfer_failure_reports_failure_and_keeps_previous_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)
    previous_manifest = created.manifest_path.read_bytes()
    previous = read_backup_manifest(backup_root)

    def _fail_transfer(*args: Any, **kwargs: Any) -> None:
        raise BackupTransferError("simulated transfer failure")

    monkeypatch.setattr(backup_module, "_transfer_objects", _fail_transfer)

    # Act
    with pytest.raises(BackupTransferError, match="simulated transfer failure"):
        create_backup(generation.database, backup_root)

    # Assert
    assert created.manifest_path.read_bytes() == previous_manifest
    status = backup_status(backup_root)
    assert status.complete
    assert status.manifest is not None
    assert status.manifest.backup_id == previous.backup_id


def test_missing_manifest_reports_not_complete(tmp_path: Path) -> None:
    # Arrange
    backup_root = tmp_path / "backup"
    backup_root.mkdir()

    # Act
    status = backup_status(backup_root)

    # Assert
    assert not status.complete
    assert status.reason == "missing_manifest"
    assert status.manifest is None


def test_truncated_manifest_reports_not_complete(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)
    manifest_path = created.manifest_path
    manifest_path.write_bytes(manifest_path.read_bytes()[:20])

    # Act
    status = backup_status(backup_root)

    # Assert
    assert not status.complete
    assert status.reason == "incomplete_backup"


def test_truncated_snapshot_reports_not_complete(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)
    snapshot = created.manifest_path.parent / DATABASE_BASENAME
    original = snapshot.read_bytes()
    snapshot.write_bytes(original[: len(original) // 2])

    # Act
    status = backup_status(backup_root)

    # Assert
    assert not status.complete
    assert status.reason == "payload_size_mismatch"


def test_removed_payload_file_reports_not_complete(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)
    removed = created.manifest_path.parent / _object_entry(read_backup_manifest(backup_root))
    removed.unlink()

    # Act
    status = backup_status(backup_root)

    # Assert
    assert not status.complete
    assert status.reason == "payload_missing"


def test_old_attempt_orphan_is_retained_while_new_attempt_restores(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    created = create_backup(generation.database, backup_root)
    orphan = created.manifest_path.parent / "orphan-payload.bin"
    orphan.write_bytes(b"orphan left behind by an earlier failed backup")

    # Act: the poisoned destination refuses a restore until re-backed-up
    with pytest.raises(BackupVerificationError):
        restore_backup(backup_root, tmp_path / "poisoned-restore")
    create_backup(generation.database, backup_root)
    result = restore_backup(backup_root, tmp_path / "restored")

    # Assert
    assert orphan.read_bytes() == b"orphan left behind by an earlier failed backup"
    assert not backup_status(created.manifest_path.parent).complete
    assert result.verified
    assert backup_status(backup_root).complete
