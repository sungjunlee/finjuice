"""SQLite Online Backup snapshots with pinned originals and completion status.

This module is the pipeline-layer snapshot surface for issue #437. It captures
one published generation with :meth:`sqlite3.Connection.backup`, holds
referenced immutable objects against GC until the completion manifest is
published, and records config/release evidence from the snapshot itself.
Transfer-only failures are reported as backup pending, never as a record
commit failure. Missing originals, an aborted snapshot, or a failed
verification are incomplete and never ``complete``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from finjuice import get_version
from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.storage.sqlite import backup as sqlite_backup
from finjuice.pipeline.storage.sqlite.backup import (
    DATABASE_BASENAME,
    BackupResult,
    backup_status,
    resolve_generation_database,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupIncompleteError,
    BackupTransferError,
    BackupVerificationError,
    RepositoryBackupError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

SNAPSHOT_KIND: Final = "finjuice.sqlite.pinned-snapshot"
PIN_DIRNAME: Final = ".finjuice-backup-pins"
_BUSY_TIMEOUT_MS: Final = 5_000
_RECORD_COMMIT_OK: Final = "ok"

SnapshotStatus = Literal["complete", "backup_pending", "incomplete_backup"]
RecordCommit = Literal["ok"]


@dataclass(frozen=True)
class PinnedArtifact:
    """One immutable source object held for the duration of a snapshot."""

    artifact_id: str
    byte_length: int
    relative_path: str
    source_path: Path


@dataclass(frozen=True)
class SnapshotReferences:
    """Config, schema, and release evidence collected from one snapshot."""

    source_artifact_ids: tuple[str, ...]
    config_revisions: tuple[dict[str, Any], ...]
    schema_version: int
    dataset_generation: str
    dataset_revision: int
    application_id: int
    release_version: str


@dataclass(frozen=True)
class SnapshotResult:
    """Receipt that distinguishes record commit success from backup outcome."""

    status: SnapshotStatus
    complete: bool
    record_commit: RecordCommit
    reason: str
    backup_root: Path
    pin_count: int
    references: SnapshotReferences | None = None
    backup_id: str | None = None
    manifest_digest: str | None = None
    database_digest: str | None = None
    source_generation: str | None = None
    dataset_revision: int | None = None
    file_count: int = 0
    byte_count: int = 0
    checks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a privacy-safe payload without filesystem paths."""
        payload: dict[str, Any] = {
            "backup_id": self.backup_id,
            "byte_count": self.byte_count,
            "checks": list(self.checks),
            "complete": self.complete,
            "dataset_revision": self.dataset_revision,
            "file_count": self.file_count,
            "kind": SNAPSHOT_KIND,
            "manifest_digest": self.manifest_digest,
            "pin_count": self.pin_count,
            "reason": self.reason,
            "record_commit": self.record_commit,
            "source_generation": self.source_generation,
            "status": self.status,
        }
        if self.references is not None:
            payload["references"] = {
                "application_id": self.references.application_id,
                "config_revision_count": len(self.references.config_revisions),
                "dataset_generation": self.references.dataset_generation,
                "dataset_revision": self.references.dataset_revision,
                "release_version": self.references.release_version,
                "schema_version": self.references.schema_version,
                "source_artifact_count": len(self.references.source_artifact_ids),
            }
        return payload


@dataclass
class ReferencePin:
    """Lease that keeps referenced originals from being GC-deleted mid-capture."""

    pin_id: str
    pin_dir: Path
    artifacts: tuple[PinnedArtifact, ...]

    @property
    def artifact_ids(self) -> frozenset[str]:
        """Return the artifact identities this lease protects."""
        return frozenset(item.artifact_id for item in self.artifacts)

    def holds(self, artifact_id: str) -> bool:
        """Return whether this lease currently protects ``artifact_id``."""
        return artifact_id in self.artifact_ids and self.pin_dir.is_dir()

    def release(self) -> None:
        """Drop the lease directory after the completion manifest is durable."""
        shutil.rmtree(self.pin_dir, ignore_errors=True)


def create_sqlite_snapshot(database: Path, destination: Path) -> SnapshotResult:
    """Capture one generation with Online Backup while referenced originals are pinned.

    A published record is treated as already committed: backup transfer failure
    returns ``status="backup_pending"`` with ``record_commit="ok"``. Missing
    originals, an aborted snapshot, or verification failure return
    ``status="incomplete_backup"`` and never ``complete=True``.

    Args:
        database: Published ``finjuice.sqlite3`` or its generation root.
        destination: Backup directory published by the inner Online Backup slice.

    Returns:
        A receipt whose ``complete`` flag is true only after a verified manifest.
    """
    source_database = _resolve_source_database(database)
    source_root = source_database.parent
    artifacts = list_referenced_artifacts(source_database)
    if any(not item.source_path.is_file() for item in artifacts):
        return _incomplete_result(
            destination,
            pin_count=len(artifacts),
            reason="missing_source",
        )
    pin = acquire_reference_pins(source_root, artifacts)
    try:
        if missing_pinned_paths(pin):
            return _incomplete_result(
                destination,
                pin_count=len(pin.artifacts),
                reason="missing_source",
            )
        return _capture_with_pins(source_database, destination, pin)
    finally:
        pin.release()


def list_referenced_artifacts(database: Path) -> tuple[PinnedArtifact, ...]:
    """Return every immutable object the live snapshot currently references."""
    source = resolve_generation_database(database)
    rows = _query_source_artifacts(source)
    root = source.parent
    return tuple(
        PinnedArtifact(
            artifact_id=str(artifact_id),
            byte_length=int(byte_length),
            relative_path=str(relative),
            source_path=root / str(relative),
        )
        for artifact_id, byte_length, relative in rows
    )


def acquire_reference_pins(
    generation_root: Path,
    artifacts: tuple[PinnedArtifact, ...],
) -> ReferencePin:
    """Hardlink referenced objects into a lease directory until snapshot completion."""
    pin_id = uuid.uuid4().hex
    pin_dir = Path(generation_root).expanduser().absolute() / PIN_DIRNAME / pin_id
    pin_dir.mkdir(mode=0o700, parents=True)
    try:
        _write_pin_lease(pin_dir, artifacts)
        for artifact in artifacts:
            pinned_name = artifact.artifact_id.replace(":", "_")
            _hardlink_or_copy(artifact.source_path, pin_dir / pinned_name)
    except OSError as exc:
        shutil.rmtree(pin_dir, ignore_errors=True)
        raise BackupError(
            "Referenced originals could not be pinned for snapshot collection.",
            code="INCOMPLETE_BACKUP",
        ) from exc
    return ReferencePin(pin_id=pin_id, pin_dir=pin_dir, artifacts=artifacts)


def missing_pinned_paths(pin: ReferencePin) -> tuple[str, ...]:
    """Return artifact IDs whose pinned bytes are missing or unreadable."""
    missing: list[str] = []
    for artifact in pin.artifacts:
        pinned = pin.pin_dir / artifact.artifact_id.replace(":", "_")
        if not artifact.source_path.is_file() and not pinned.is_file():
            missing.append(artifact.artifact_id)
            continue
        if not pinned.is_file():
            missing.append(artifact.artifact_id)
    return tuple(missing)


def gc_unpinned_objects(generation_root: Path, pin: ReferencePin | None = None) -> tuple[str, ...]:
    """Delete object files that no active pin lease protects.

    This helper exists so tests can prove collection pins block GC. It never
    unlinks an object listed on ``pin`` or any other live lease under
    ``.finjuice-backup-pins``.
    """
    root = Path(generation_root).expanduser().absolute()
    protected = set(_all_pinned_artifact_ids(root))
    if pin is not None:
        protected.update(pin.artifact_ids)
    deleted: list[str] = []
    objects = GenerationPaths(root).sha256_objects
    if not objects.is_dir():
        return ()
    for path in sorted(objects.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        artifact_id = f"sha256:{path.name}"
        if artifact_id in protected:
            continue
        path.unlink()
        deleted.append(artifact_id)
    return tuple(deleted)


def snapshot_status(backup_root: Path) -> SnapshotResult:
    """Re-verify a backup directory without treating incompleteness as success."""
    root = Path(backup_root).expanduser().absolute()
    status = backup_status(root)
    if not status.complete:
        return SnapshotResult(
            status="incomplete_backup",
            complete=False,
            record_commit=_RECORD_COMMIT_OK,
            reason=status.reason,
            backup_root=root,
            pin_count=0,
        )
    references = collect_snapshot_references(root)
    manifest = status.manifest
    assert manifest is not None
    database_digest = next(
        (entry.sha256 for entry in manifest.files if entry.path == DATABASE_BASENAME),
        None,
    )
    return SnapshotResult(
        status="complete",
        complete=True,
        record_commit=_RECORD_COMMIT_OK,
        reason="complete",
        backup_root=root,
        pin_count=len(references.source_artifact_ids),
        references=references,
        backup_id=manifest.backup_id,
        manifest_digest=manifest.manifest_digest,
        database_digest=database_digest,
        source_generation=manifest.source_generation,
        dataset_revision=manifest.dataset_revision,
        file_count=len(manifest.files),
        byte_count=manifest.byte_count,
        checks=("manifest_digest", "payload_digests"),
    )


def collect_snapshot_references(backup_root: Path) -> SnapshotReferences:
    """Read config/release evidence from the captured snapshot database."""
    database = Path(backup_root).expanduser().absolute() / DATABASE_BASENAME
    connection = _connect_readonly(database)
    try:
        meta = connection.execute(
            "SELECT application_id, schema_version, dataset_generation, dataset_revision "
            "FROM repository_meta WHERE singleton = 1"
        ).fetchone()
        if meta is None:
            raise BackupError(
                "Snapshot is missing repository identity; the backup is incomplete.",
                code="INCOMPLETE_BACKUP",
            )
        artifacts = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT source_artifact_id FROM source_artifacts ORDER BY source_artifact_id"
            )
        )
        revisions = tuple(
            {
                "config_kind": str(row[0]),
                "source_artifact_id": str(row[1]),
                "parsed_status": str(row[2]),
            }
            for row in connection.execute(
                "SELECT config_kind, source_artifact_id, parsed_status "
                "FROM config_revisions ORDER BY entity_id"
            )
        )
    finally:
        connection.close()
    return SnapshotReferences(
        source_artifact_ids=artifacts,
        config_revisions=revisions,
        schema_version=int(meta[1]),
        dataset_generation=str(meta[2]),
        dataset_revision=int(meta[3]),
        application_id=int(meta[0]),
        release_version=get_version(),
    )


def _capture_with_pins(
    source_database: Path,
    destination: Path,
    pin: ReferencePin,
) -> SnapshotResult:
    """Run Online Backup while the pin lease is held, then collect references."""
    try:
        inner = _publish_generation_backup(source_database, destination)
    except BackupTransferError as exc:
        return _classify_transfer_failure(destination, pin, exc)
    except (BackupVerificationError, BackupIncompleteError):
        return _incomplete_result(
            destination,
            pin_count=len(pin.artifacts),
            reason="verification_failed",
        )
    except sqlite3.Error:
        return _incomplete_result(
            destination,
            pin_count=len(pin.artifacts),
            reason="snapshot_aborted",
        )
    except RepositoryPathError as exc:
        raise BackupError(
            "Backup destination could not be prepared.",
            code="INVALID_ARGS",
        ) from exc
    return _complete_result(inner, pin)


def _publish_generation_backup(source_database: Path, destination: Path) -> BackupResult:
    """Transfer one generation through the SQLite Online Backup API.

    Isolated so tests can inject transfer, abort, and verification failures
    without treating the published record as failed.
    """
    return sqlite_backup.create_backup(source_database, destination)


def _complete_result(inner: BackupResult, pin: ReferencePin) -> SnapshotResult:
    """Build a success receipt only after the inner completion manifest exists."""
    if not inner.complete:
        return _incomplete_result(
            inner.backup_root,
            pin_count=len(pin.artifacts),
            reason="incomplete_backup",
        )
    references = collect_snapshot_references(inner.backup_root)
    return SnapshotResult(
        status="complete",
        complete=True,
        record_commit=_RECORD_COMMIT_OK,
        reason="complete",
        backup_root=inner.backup_root,
        pin_count=len(pin.artifacts),
        references=references,
        backup_id=inner.backup_id,
        manifest_digest=inner.manifest_digest,
        database_digest=inner.database_digest,
        source_generation=inner.source_generation,
        dataset_revision=inner.dataset_revision,
        file_count=inner.file_count,
        byte_count=inner.byte_count,
        checks=("integrity_check", "foreign_key_check", "payload_digests"),
    )


def _classify_transfer_failure(
    destination: Path,
    pin: ReferencePin,
    exc: BackupTransferError,
) -> SnapshotResult:
    """Map inner transfer errors onto pending versus incomplete backup states."""
    reason = exc.reason
    message = str(exc).lower()
    if "online backup" in message or "snapshot" in message:
        return _incomplete_result(
            destination,
            pin_count=len(pin.artifacts),
            reason="snapshot_aborted",
        )
    if "source object" in message or "referenced" in message:
        return _incomplete_result(
            destination,
            pin_count=len(pin.artifacts),
            reason="missing_source",
        )
    return SnapshotResult(
        status="backup_pending",
        complete=False,
        record_commit=_RECORD_COMMIT_OK,
        reason=reason,
        backup_root=Path(destination).expanduser().absolute(),
        pin_count=len(pin.artifacts),
    )


def _incomplete_result(destination: Path, *, pin_count: int, reason: str) -> SnapshotResult:
    """Return a non-success receipt that never claims a complete backup."""
    return SnapshotResult(
        status="incomplete_backup",
        complete=False,
        record_commit=_RECORD_COMMIT_OK,
        reason=reason,
        backup_root=Path(destination).expanduser().absolute(),
        pin_count=pin_count,
    )


def _resolve_source_database(database: Path) -> Path:
    """Resolve a generation root or database path, mapping storage errors."""
    try:
        return resolve_generation_database(database)
    except (RepositoryBackupError, RepositoryPathError) as exc:
        raise BackupError(
            "No published authoritative database was found for the requested snapshot.",
            code="INVALID_ARGS",
        ) from exc


def _query_source_artifacts(database: Path) -> list[tuple[Any, Any, Any]]:
    """Return source-artifact rows from a read-only connection."""
    connection = _connect_readonly(database)
    try:
        return connection.execute(
            "SELECT source_artifact_id, byte_length, object_path FROM source_artifacts "
            "ORDER BY source_artifact_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise BackupError(
            "Snapshot source artifacts could not be listed.",
            code="INCOMPLETE_BACKUP",
        ) from exc
    finally:
        connection.close()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Open one read-only SQLite connection with a bounded busy timeout."""
    uri = f"{path.absolute().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    except sqlite3.Error as exc:
        raise BackupError(
            "SQLite file could not be opened for snapshot.",
            code="INCOMPLETE_BACKUP",
        ) from exc
    return connection


def _write_pin_lease(pin_dir: Path, artifacts: tuple[PinnedArtifact, ...]) -> None:
    """Persist the protected artifact set so cooperative GC can honor the lease."""
    payload = {
        "artifact_ids": [item.artifact_id for item in artifacts],
        "kind": SNAPSHOT_KIND,
    }
    lease = pin_dir / "lease.json"
    lease.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(lease, 0o600)


def _hardlink_or_copy(source: Path, destination: Path) -> None:
    """Hold one object's inode (or a copy) so GC cannot drop bytes mid-capture."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _all_pinned_artifact_ids(generation_root: Path) -> frozenset[str]:
    """Return every artifact ID recorded on a live pin lease."""
    pins_root = generation_root / PIN_DIRNAME
    if not pins_root.is_dir():
        return frozenset()
    held: set[str] = set()
    for lease in pins_root.glob("*/lease.json"):
        try:
            payload = json.loads(lease.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ids = payload.get("artifact_ids", [])
        if isinstance(ids, list):
            held.update(str(item) for item in ids)
    return frozenset(held)


__all__ = [
    "PIN_DIRNAME",
    "SNAPSHOT_KIND",
    "PinnedArtifact",
    "ReferencePin",
    "SnapshotReferences",
    "SnapshotResult",
    "acquire_reference_pins",
    "collect_snapshot_references",
    "create_sqlite_snapshot",
    "gc_unpinned_objects",
    "list_referenced_artifacts",
    "missing_pinned_paths",
    "snapshot_status",
]
