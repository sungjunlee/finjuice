"""Identity and acceptance tests for SQLite snapshot + isolated restore (issue #437)."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from finjuice.pipeline.backup import snapshot as snapshot_module
from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.restore import (
    apply_copy_correction,
    query_restored_copy,
    restore_sqlite_snapshot,
    restored_mutation_smoke,
)
from finjuice.pipeline.backup.snapshot import (
    acquire_reference_pins,
    create_sqlite_snapshot,
    gc_unpinned_objects,
    list_referenced_artifacts,
    snapshot_status,
)
from finjuice.pipeline.storage.sqlite import (
    ConfigRevisionRecord,
    GenerationPaths,
    RepositoryBuilder,
    SourceOccurrenceRecord,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite.backup import DATABASE_BASENAME, MANIFEST_FILENAME
from finjuice.pipeline.storage.sqlite.errors import BackupTransferError, BackupVerificationError

SNAPSHOT_MODULE = "finjuice.pipeline.backup.snapshot"
RESTORE_MODULE = "finjuice.pipeline.backup.restore"


def test_snapshot_restore_names_live_in_backup_package() -> None:
    """Snapshot and restore APIs are defined in the owned backup modules."""
    assert create_sqlite_snapshot.__module__ == SNAPSHOT_MODULE
    assert snapshot_status.__module__ == SNAPSHOT_MODULE
    assert acquire_reference_pins.__module__ == SNAPSHOT_MODULE
    assert restore_sqlite_snapshot.__module__ == RESTORE_MODULE
    assert query_restored_copy.__module__ == RESTORE_MODULE
    assert apply_copy_correction.__module__ == RESTORE_MODULE
    assert restored_mutation_smoke.__module__ == RESTORE_MODULE
    assert "def create_sqlite_snapshot" in Path(
        "src/finjuice/pipeline/backup/snapshot.py"
    ).read_text(encoding="utf-8")
    assert "def restore_sqlite_snapshot" in Path(
        "src/finjuice/pipeline/backup/restore.py"
    ).read_text(encoding="utf-8")
    assert not Path("src/finjuice/pipeline/backup/drill.py").exists()
    assert not Path("src/finjuice/pipeline/backup/schedule.py").exists()


def _build_generation(
    root: Path, *, source_bytes: bytes = b"synthetic snapshot source"
) -> GenerationPaths:
    """Publish one synthetic generation with a config revision and source object."""
    paths = GenerationPaths(root)
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        artifact = builder.publish_source(io.BytesIO(source_bytes))
        occurrence_id = new_entity_id()
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="synthetic",
            )
        )
        builder.add_config_revision(
            ConfigRevisionRecord(
                revision_id=new_entity_id(),
                config_kind="rules",
                artifact_id=artifact.artifact_id,
                occurrence_id=occurrence_id,
                parsed_status="parsed",
                canonical_payload={"rules": []},
            )
        )
        builder.finalize()
    return paths


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_snapshot_during_writes_restores_with_integrity_fk_and_hash(tmp_path: Path) -> None:
    """AC: a snapshot taken during writes restores and passes integrity/FK/hash checks."""
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    stop = threading.Event()

    def _writer() -> None:
        connection = sqlite3.connect(generation.database, timeout=5.0)
        try:
            while not stop.is_set():
                party_id = str(uuid4())
                connection.execute(
                    "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'party')",
                    (party_id,),
                )
                connection.execute(
                    "INSERT INTO parties (entity_id, entity_kind, party_kind, display_name) "
                    "VALUES (?, 'party', 'unknown', ?)",
                    (party_id, "synthetic-writer"),
                )
                connection.commit()
                time.sleep(0.005)
        finally:
            connection.close()

    worker = threading.Thread(target=_writer, daemon=True)
    worker.start()
    try:
        # Act
        created = create_sqlite_snapshot(generation.database, tmp_path / "backup")
        restored = restore_sqlite_snapshot(tmp_path / "backup", tmp_path / "restored")
        status = snapshot_status(tmp_path / "backup")
    finally:
        stop.set()
        worker.join(timeout=5)

    # Assert
    assert created.complete
    assert created.record_commit == "ok"
    assert created.status == "complete"
    assert created.references is not None
    assert created.references.config_revisions
    assert created.references.release_version
    assert restored.verified
    assert {"integrity_check", "foreign_key_check", "payload_digests"} <= set(restored.checks)
    assert status.complete
    assert status.reason == "complete"
    view = query_restored_copy(tmp_path / "restored")
    assert view.config_revisions
    assert view.source_artifacts


def test_restored_copy_query_correction_and_rebackup(tmp_path: Path) -> None:
    """AC: restored query and manual correction replay through copy change→query→re-backup."""
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    source_digest = _file_digest(generation.database)
    source_ino = generation.database.stat().st_ino
    created = create_sqlite_snapshot(generation.database, tmp_path / "backup")

    # Act
    smoke = restored_mutation_smoke(tmp_path / "backup", tmp_path / "workspace")

    # Assert
    assert created.complete
    assert smoke.first_restore.verified
    assert smoke.second_restore.verified
    assert smoke.correction.display_name == "synthetic-copy-correction"
    before_ids = {row["entity_id"] for row in smoke.before.parties}
    after_ids = {row["entity_id"] for row in smoke.after.parties}
    replayed_ids = {row["entity_id"] for row in smoke.replayed.parties}
    assert smoke.correction.party_id not in before_ids
    assert smoke.correction.party_id in after_ids
    assert smoke.correction.party_id in replayed_ids
    assert smoke.after.dataset_revision == smoke.before.dataset_revision + 1
    assert smoke.replayed.dataset_revision == smoke.after.dataset_revision
    assert smoke.rebackup.complete
    assert smoke.rebackup.dataset_revision == smoke.after.dataset_revision
    assert _file_digest(generation.database) == source_digest
    assert generation.database.stat().st_ino == source_ino


def test_transfer_failure_reports_backup_pending_not_record_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC: transfer-only failure reports backup pending and does not imply record failure."""
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    first = create_sqlite_snapshot(generation.database, tmp_path / "backup")
    previous_manifest = (tmp_path / "backup" / MANIFEST_FILENAME).read_bytes()

    def _fail_transfer(*args: Any, **kwargs: Any) -> Any:
        raise BackupTransferError("simulated payload transfer failure")

    monkeypatch.setattr(snapshot_module, "_publish_generation_backup", _fail_transfer)

    # Act
    pending = create_sqlite_snapshot(generation.database, tmp_path / "backup")

    # Assert
    assert first.complete
    assert first.record_commit == "ok"
    assert pending.complete is False
    assert pending.status == "backup_pending"
    assert pending.record_commit == "ok"
    assert pending.reason == "transfer_failed"
    assert pending.status != "record_failed"
    assert (tmp_path / "backup" / MANIFEST_FILENAME).read_bytes() == previous_manifest
    assert snapshot_status(tmp_path / "backup").complete


def test_missing_source_interrupted_snapshot_and_verification_are_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC: missing originals, aborted snapshots, and failed verification are not success."""
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    artifacts = list_referenced_artifacts(generation.database)
    assert artifacts
    artifacts[0].source_path.unlink()

    # Act
    missing = create_sqlite_snapshot(generation.database, tmp_path / "missing")

    # Assert
    assert missing.complete is False
    assert missing.status == "incomplete_backup"
    assert missing.reason == "missing_source"
    assert missing.record_commit == "ok"
    assert not (tmp_path / "missing" / MANIFEST_FILENAME).is_file()

    generation = _build_generation(tmp_path / "generation-abort", source_bytes=b"abort source")

    def _abort(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.Error("simulated snapshot abort")

    monkeypatch.setattr(snapshot_module, "_publish_generation_backup", _abort)
    aborted = create_sqlite_snapshot(generation.database, tmp_path / "aborted")
    assert aborted.complete is False
    assert aborted.status == "incomplete_backup"
    assert aborted.reason == "snapshot_aborted"
    assert not (tmp_path / "aborted" / MANIFEST_FILENAME).is_file()

    def _fail_verify(*args: Any, **kwargs: Any) -> Any:
        raise BackupVerificationError("simulated verification failure")

    monkeypatch.setattr(snapshot_module, "_publish_generation_backup", _fail_verify)
    failed = create_sqlite_snapshot(generation.database, tmp_path / "verify")
    assert failed.complete is False
    assert failed.status == "incomplete_backup"
    assert failed.reason == "verification_failed"
    assert failed.to_dict()["complete"] is False


def test_reference_pins_block_gc_until_manifest_is_published(tmp_path: Path) -> None:
    """Referenced originals stay pinned so cooperative GC cannot drop them mid-capture."""
    # Arrange
    generation = _build_generation(tmp_path / "generation")
    artifacts = list_referenced_artifacts(generation.database)
    pin = acquire_reference_pins(generation.root, artifacts)

    # Act
    deleted_while_held = gc_unpinned_objects(generation.root, pin)

    # Assert
    assert artifacts[0].artifact_id not in deleted_while_held
    assert artifacts[0].source_path.is_file()
    assert pin.holds(artifacts[0].artifact_id)
    pin.release()
    created = create_sqlite_snapshot(generation.database, tmp_path / "backup")
    assert created.complete
    assert created.pin_count == len(artifacts)
    restored = restore_sqlite_snapshot(tmp_path / "backup", tmp_path / "restored")
    assert restored.verified


def test_incomplete_backup_cannot_be_restored(tmp_path: Path) -> None:
    """A directory without a completion manifest is never treated as a successful restore."""
    # Arrange
    backup_root = tmp_path / "empty"
    backup_root.mkdir()

    # Act / Assert
    with pytest.raises(BackupError) as exc_info:
        restore_sqlite_snapshot(backup_root, tmp_path / "restored")
    assert exc_info.value.code == "INCOMPLETE_BACKUP"
    assert not (tmp_path / "restored" / DATABASE_BASENAME).exists()
    status = snapshot_status(backup_root)
    assert status.complete is False
    assert status.status == "incomplete_backup"
