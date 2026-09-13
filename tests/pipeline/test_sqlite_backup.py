"""Synthetic tests for generation backup creation, status, and restore."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder
from finjuice.pipeline.storage.sqlite import backup as backup_module
from finjuice.pipeline.storage.sqlite.backup import (
    ACTIVATION_ABSENT,
    DATABASE_BASENAME,
    MANIFEST_FILENAME,
    BackupManifest,
    backup_status,
    create_backup,
    read_backup_manifest,
    resolve_backup_payload_root,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupTransferError,
    BackupVerificationError,
    RepositoryBackupError,
)
from finjuice.pipeline.storage.sqlite.records import (
    ConfigRevisionRecord,
    PartyRecord,
    SourceOccurrenceRecord,
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


def _payload_root(backup_root: Path) -> Path:
    """Return the current attempt directory for one backup pointer root."""
    return resolve_backup_payload_root(backup_root)


def _object_entry(manifest: BackupManifest) -> str:
    """Return the manifest path of the first backed-up source object."""
    return next(entry.path for entry in manifest.files if entry.role == "object")


def _build_generation_with_config(root: Path) -> GenerationPaths:
    """Publish a generation that references config/release artifacts."""
    paths = GenerationPaths(root)
    occurrence_id = str(uuid4())
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        source = builder.publish_source(io.BytesIO(b"synthetic backup source bytes"))
        config = builder.publish_source(io.BytesIO(b"rules: []\n"))
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=config.artifact_id,
                occurrence_kind="rules_yaml",
                original_filename="rules.yaml",
            )
        )
        builder.add_config_revision(
            ConfigRevisionRecord(
                revision_id=str(uuid4()),
                config_kind="rules",
                artifact_id=config.artifact_id,
                occurrence_id=occurrence_id,
                parsed_status="parsed",
                canonical_payload={"rules": []},
            )
        )
        builder.add_party(
            PartyRecord(party_id=str(uuid4()), party_kind="person", display_name="before"),
        )
        builder.finalize()
        assert source.artifact_id
    return paths


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
    create_backup(generation.database, backup_root)
    previous_manifest = (_payload_root(backup_root) / MANIFEST_FILENAME).read_bytes()
    previous = read_backup_manifest(backup_root)
    previous_db = (_payload_root(backup_root) / DATABASE_BASENAME).read_bytes()

    def _fail_transfer(*args: Any, **kwargs: Any) -> None:
        raise BackupTransferError("simulated transfer failure")

    monkeypatch.setattr(backup_module, "_transfer_pinned_objects", _fail_transfer)

    # Act
    with pytest.raises(BackupTransferError, match="simulated transfer failure"):
        create_backup(generation.database, backup_root)

    # Assert
    assert (_payload_root(backup_root) / MANIFEST_FILENAME).read_bytes() == previous_manifest
    assert (_payload_root(backup_root) / DATABASE_BASENAME).read_bytes() == previous_db
    status = backup_status(backup_root)
    assert status.complete
    assert status.manifest is not None
    assert status.manifest.backup_id == previous.backup_id
    restored = restore_backup(backup_root, tmp_path / "after-transfer-failure")
    assert restored.source_generation == previous.source_generation


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
    create_backup(generation.database, backup_root)
    manifest_path = _payload_root(backup_root) / MANIFEST_FILENAME
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
    create_backup(generation.database, backup_root)
    snapshot = _payload_root(backup_root) / DATABASE_BASENAME
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
    create_backup(generation.database, backup_root)
    removed = _payload_root(backup_root) / _object_entry(read_backup_manifest(backup_root))
    removed.unlink()

    # Act
    status = backup_status(backup_root)

    # Assert
    assert not status.complete
    assert status.reason == "payload_missing"


def test_orphan_payload_is_pruned_by_create_and_restore_succeeds(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    create_backup(generation.database, backup_root)
    orphan = _payload_root(backup_root) / "orphan-payload.bin"
    orphan.write_bytes(b"orphan left behind by an earlier failed backup")

    # Act: the poisoned attempt refuses a restore until a new attempt is published
    with pytest.raises(BackupVerificationError):
        restore_backup(backup_root, tmp_path / "poisoned-restore")
    create_backup(generation.database, backup_root)
    result = restore_backup(backup_root, tmp_path / "restored")

    # Assert
    assert not (_payload_root(backup_root) / "orphan-payload.bin").exists()
    assert result.verified
    assert backup_status(backup_root).complete


def test_late_manifest_failure_preserves_previous_attempt_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    first = _build_generation(tmp_path / "generation-a")
    second = _build_generation(tmp_path / "generation-b")
    backup_root = tmp_path / "backup"
    first_result = create_backup(first.database, backup_root)
    previous_id = first_result.backup_id
    previous_db = (_payload_root(backup_root) / DATABASE_BASENAME).read_bytes()

    def _fail_manifest(*args: Any, **kwargs: Any) -> BackupManifest:
        raise BackupTransferError("injected late manifest failure")

    monkeypatch.setattr(backup_module, "_write_manifest", _fail_manifest)

    # Act
    with pytest.raises(BackupTransferError, match="injected late manifest failure"):
        create_backup(second.database, backup_root)

    # Assert: previous attempt payload is still complete and restorable
    status = backup_status(backup_root)
    assert status.complete
    assert status.reason == "complete"
    assert status.manifest is not None
    assert status.manifest.backup_id == previous_id
    assert (_payload_root(backup_root) / DATABASE_BASENAME).read_bytes() == previous_db
    restored = restore_backup(backup_root, tmp_path / "restored-previous")
    assert restored.source_generation == first_result.source_generation


def test_directory_fsync_warning_is_not_a_late_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")

    def _warn_only(directory: Path, warnings: list[str]) -> None:
        warnings.append("directory_fsync_failed")

    monkeypatch.setattr(backup_module, "_record_directory_fsync", _warn_only)

    # Act
    created = create_backup(generation.database, tmp_path / "backup")

    # Assert
    assert created.complete
    assert "directory_fsync_failed" in created.warnings
    assert backup_status(tmp_path / "backup").complete


def test_partial_writes_still_complete_and_zero_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    real_write = os.write

    def _one_byte(fd: int, data: Any) -> int:
        view = memoryview(data)
        if not view:
            return real_write(fd, data)
        return real_write(fd, view[:1])

    monkeypatch.setattr(backup_module.os, "write", _one_byte)

    # Act
    created = create_backup(generation.database, tmp_path / "backup")

    # Assert
    assert created.complete
    assert backup_status(tmp_path / "backup").complete

    def _zero_write(descriptor: int, data: bytes) -> None:
        raise BackupTransferError("Backup payload write made no progress.")

    monkeypatch.setattr(backup_module, "_write_all", _zero_write)
    with pytest.raises(BackupTransferError, match="no progress"):
        create_backup(generation.database, tmp_path / "backup-zero")
    assert not backup_status(tmp_path / "backup-zero").complete


def test_gc_pin_keeps_source_objects_collectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    real_pin = backup_module._pin_referenced_objects

    def _pin_then_unlink(
        source_database: Path,
        connection: sqlite3.Connection,
        backup_root: Path,
    ) -> Any:
        pins = real_pin(source_database, connection, backup_root)
        objects = GenerationPaths(source_database.parent).sha256_objects
        for path in objects.rglob("*"):
            if path.is_file():
                path.unlink()
        return pins

    monkeypatch.setattr(backup_module, "_pin_referenced_objects", _pin_then_unlink)

    # Act
    created = create_backup(generation.database, tmp_path / "backup")
    restored = restore_backup(tmp_path / "backup", tmp_path / "restored")

    # Assert
    assert created.complete
    assert restored.verified
    assert restored.generation_status == "inactive"


def test_strict_status_rejects_symlink_unknown_field_and_duplicate(
    tmp_path: Path,
) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    backup_root = tmp_path / "backup"
    create_backup(generation.database, backup_root)
    payload = _payload_root(backup_root)
    manifest = read_backup_manifest(backup_root)
    target = payload / _object_entry(manifest)
    external = tmp_path / "same-bytes.bin"
    external.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(external)

    # Act / Assert
    status = backup_status(backup_root)
    assert not status.complete
    assert status.reason == "payload_not_regular_file"

    create_backup(generation.database, tmp_path / "backup-fields")
    manifest_path = _payload_root(tmp_path / "backup-fields") / MANIFEST_FILENAME
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["unexpected"] = "ignored-by-digest"
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    unknown = backup_status(tmp_path / "backup-fields")
    assert not unknown.complete
    assert unknown.reason == "incomplete_backup"

    create_backup(generation.database, tmp_path / "backup-dup")
    dup_path = _payload_root(tmp_path / "backup-dup") / MANIFEST_FILENAME
    duplicated = json.loads(dup_path.read_text(encoding="utf-8"))
    duplicated["files"].append(duplicated["files"][0])
    dup_path.write_text(json.dumps(duplicated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    duplicate = backup_status(tmp_path / "backup-dup")
    assert not duplicate.complete
    assert duplicate.reason == "incomplete_backup"


def test_direct_v1_is_restorable_and_recreate_is_refused(tmp_path: Path) -> None:
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    attempt_root = tmp_path / "attempt-layout"
    create_backup(generation.database, attempt_root)
    v1 = tmp_path / "v1"
    shutil.copytree(_payload_root(attempt_root), v1)

    # Act
    restored = restore_backup(v1, tmp_path / "from-v1")
    with pytest.raises(RepositoryBackupError, match="direct v1"):
        create_backup(generation.database, v1)

    # Assert
    assert restored.verified
    assert (v1 / MANIFEST_FILENAME).is_file()
    assert (v1 / DATABASE_BASENAME).is_file()


def test_config_release_collected_and_restored_copy_correction_roundtrip(
    tmp_path: Path,
) -> None:
    # Arrange
    generation = _build_generation_with_config(tmp_path / "generation")
    original_party = _party_name(generation.database)
    created = create_backup(generation.database, tmp_path / "backup")
    restored = restore_backup(tmp_path / "backup", tmp_path / "restored")

    # Act: mutate only the isolated restored copy, query it, then re-backup
    _correct_party_name(tmp_path / "restored" / DATABASE_BASENAME, "after-correction")
    queried = _party_name(tmp_path / "restored" / DATABASE_BASENAME)
    second = create_backup(tmp_path / "restored" / DATABASE_BASENAME, tmp_path / "backup-2")
    second_restore = restore_backup(tmp_path / "backup-2", tmp_path / "restored-2")

    # Assert
    assert created.complete
    assert created.config_revision_count == 1
    assert created.activation_binding == ACTIVATION_ABSENT
    assert restored.generation_status == "inactive"
    assert original_party == "before"
    assert queried == "after-correction"
    assert _party_name(generation.database) == "before"
    assert _party_name(tmp_path / "restored-2" / DATABASE_BASENAME) == "after-correction"
    assert second.complete
    assert second_restore.verified
    assert second.source_generation == restored.source_generation


def _party_name(database: Path) -> str:
    """Return the synthetic party display name via the repository reader."""
    from finjuice.pipeline.storage.sqlite import RepositoryReader

    with RepositoryReader(database) as reader:
        rows = reader.rows("parties")
    assert rows
    return str(rows[0]["display_name"])


def _correct_party_name(database: Path, name: str) -> None:
    """Apply a manual correction only on an isolated restored copy."""
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("UPDATE parties SET display_name = ?", (name,))
        connection.execute(
            "UPDATE repository_meta SET dataset_revision = dataset_revision + 1",
        )
        connection.commit()
    finally:
        connection.close()
