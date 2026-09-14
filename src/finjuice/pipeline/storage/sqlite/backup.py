"""SQLite snapshots published as independent, verified backup attempts.

New backups use immutable attempt directories and a final current pointer. Failure
before pointer publication cannot overwrite a prior attempt. A durability failure
is an error even if an atomic rename has already happened; published attempts are
retained for independent verification. Direct version-1 backups remain readable.

These receipts verify the local snapshot and recorded object bytes. External
activation/release binding, reference GC pins and operational recovery acceptance
remain separate requirements. Restore copies into a separate empty directory and
checks SQLite integrity, foreign keys, application invariants and object hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from finjuice.pipeline.storage.atomic_files import _write_all
from finjuice.pipeline.storage.sqlite.backup_publication import (
    begin_attempt,
    discard_attempt,
    fsync_attempt_tree,
    prepare_container,
    publish_attempt,
    publish_current_pointer,
)
from finjuice.pipeline.storage.sqlite.backup_verify import (
    copy_regular_file,
    fingerprint_regular_file,
    read_regular_bytes,
    resolve_backup_input,
    verify_manifest_bytes,
    verify_payload,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupIncompleteError,
    BackupTransferError,
    BackupVerificationError,
    ObjectCorruptionError,
    ObjectStoreError,
    RepositoryBackupError,
    RepositoryIntegrityError,
    RepositoryPathError,
    RepositoryVersionError,
)
from finjuice.pipeline.storage.sqlite.objects import (
    SourceArtifact,
    SourceObjectStore,
    _assert_no_symlink_ancestors,
    _mkdir_checked,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import (
    RepositoryInfo,
    _connect_builder,
    _copy_source_objects,
    _fsync_directory,
    _normalize_journal_mode,
    _read_info,
    _validate_connection,
)

BACKUP_KIND: Final = "finjuice.sqlite.generation-backup"
BACKUP_SCHEMA_VERSION: Final = 1
MANIFEST_FILENAME: Final = "backup-manifest.json"
DATABASE_BASENAME: Final = "finjuice.sqlite3"
OBJECT_NAMESPACE: Final = "objects"

_STAGING_PREFIX: Final = ".finjuice-backup-"
_BUSY_TIMEOUT_MS: Final = 5_000
_DATABASE_ROLE: Final = "database"
_OBJECT_ROLE: Final = "object"

#: Checks a completed restore proves before the copy is reported usable.
RESTORE_CHECKS: Final = (
    "manifest_digest",
    "payload_digests",
    "integrity_check",
    "foreign_key_check",
    "application_invariants",
    "source_objects",
    "generation_identity",
)


@dataclass(frozen=True)
class BackupFileEntry:
    """One digest-recorded file inside a backup directory."""

    path: str
    sha256: str
    byte_length: int

    @property
    def role(self) -> str:
        """Return ``database`` for the snapshot and ``object`` for source bytes."""
        return _DATABASE_ROLE if self.path == DATABASE_BASENAME else _OBJECT_ROLE

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical manifest representation of this entry."""
        return {"byte_length": self.byte_length, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class BackupManifest:
    """A parsed and self-digest-verified backup completion manifest."""

    schema_version: int
    kind: str
    backup_id: str
    created_at: str
    source_generation: str
    dataset_revision: int
    files: tuple[BackupFileEntry, ...]
    manifest_digest: str

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical payload covered by :attr:`manifest_digest`."""
        return {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "dataset_revision": self.dataset_revision,
            "files": [entry.to_payload() for entry in self.files],
            "kind": self.kind,
            "schema_version": self.schema_version,
            "source_generation": self.source_generation,
        }

    @property
    def byte_count(self) -> int:
        """Return the total recorded payload size in bytes."""
        return sum(entry.byte_length for entry in self.files)

    def entry(self, path: str) -> BackupFileEntry:
        """Return the manifest entry for one backup-relative payload path."""
        for candidate in self.files:
            if candidate.path == path:
                return candidate
        raise BackupIncompleteError("Backup manifest does not record the requested payload file.")


@dataclass(frozen=True)
class BackupResult:
    """Receipt for one completed generation backup."""

    backup_root: Path
    manifest_path: Path
    backup_id: str
    source_generation: str
    dataset_revision: int
    file_count: int
    byte_count: int
    database_digest: str
    manifest_digest: str
    complete: bool = True
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe CLI payload (no filesystem paths)."""
        return {
            "backup_id": self.backup_id,
            "backup_kind": BACKUP_KIND,
            "byte_count": self.byte_count,
            "complete": self.complete,
            "database_digest": self.database_digest,
            "dataset_revision": self.dataset_revision,
            "file_count": self.file_count,
            "manifest_digest": self.manifest_digest,
            "manifest_schema_version": BACKUP_SCHEMA_VERSION,
            "source_generation": self.source_generation,
            "status": "complete",
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BackupStatus:
    """Completeness verdict for one backup directory."""

    backup_root: Path
    complete: bool
    reason: str
    manifest: BackupManifest | None

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe CLI payload (no filesystem paths)."""
        manifest = self.manifest
        return {
            "byte_count": 0 if manifest is None else manifest.byte_count,
            "complete": self.complete,
            "file_count": 0 if manifest is None else len(manifest.files),
            "manifest_digest": None if manifest is None else manifest.manifest_digest,
            "reason": self.reason,
            "source_generation": None if manifest is None else manifest.source_generation,
        }


@dataclass(frozen=True)
class RestoreResult:
    """Receipt for one verified restore of a backup directory."""

    backup_root: Path
    destination: Path
    database: Path
    source_generation: str
    dataset_revision: int
    file_count: int
    byte_count: int
    manifest_digest: str
    verified: bool = True
    checks: tuple[str, ...] = RESTORE_CHECKS
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe CLI payload (no filesystem paths)."""
        return {
            "byte_count": self.byte_count,
            "checks": list(self.checks),
            "dataset_revision": self.dataset_revision,
            "file_count": self.file_count,
            "manifest_digest": self.manifest_digest,
            "source_generation": self.source_generation,
            "status": "restored",
            "verified": self.verified,
            "warnings": list(self.warnings),
        }


def resolve_generation_database(generation: Path) -> Path:
    """Return the published repository database for a generation root or DB path.

    Args:
        generation: A generation root directory or its ``finjuice.sqlite3`` file.

    Returns:
        Absolute path to the published authoritative database.

    Raises:
        RepositoryPathError: If the path is reached through a symlink.
        RepositoryBackupError: If no published database exists at that path.
    """
    candidate = generation.expanduser().absolute()
    if candidate.name != DATABASE_BASENAME:
        candidate = GenerationPaths(candidate).database
    _assert_no_symlink_ancestors(candidate, allow_missing=True)
    if not candidate.is_file():
        raise RepositoryBackupError(
            "No published authoritative database was found for the requested generation.",
        )
    return candidate


def create_backup(database: Path, destination_root: Path) -> BackupResult:
    """Publish an independent snapshot attempt, then advance its current pointer.

    Repeated captures preserve previous attempts and identical source payload
    digests. A direct version-1 destination requires a new backup container; it
    is never converted or pruned in place. Failed publication raises without a
    complete receipt, including failures after the pointer rename but before fsync.
    """
    source_database = resolve_generation_database(database)
    backup_root = prepare_container(destination_root, source_database.parent)
    workspace = begin_attempt(backup_root)
    try:
        manifest = _capture_attempt(source_database, workspace.staging_root)
        verify_payload(workspace.staging_root, manifest)
        published = publish_attempt(workspace)
        verify_payload(published, manifest)
        manifest_path = published / MANIFEST_FILENAME
        publish_current_pointer(backup_root, published, manifest_path, manifest.manifest_digest)
        selected_root, selected_manifest, _ = resolve_backup_input(backup_root)
        if selected_root != published or selected_manifest != manifest:
            raise BackupTransferError("Backup selection changed during publication.")
        return BackupResult(
            backup_root=backup_root,
            manifest_path=manifest_path,
            backup_id=manifest.backup_id,
            source_generation=manifest.source_generation,
            dataset_revision=manifest.dataset_revision,
            file_count=len(manifest.files),
            byte_count=manifest.byte_count,
            database_digest=manifest.entry(DATABASE_BASENAME).sha256,
            manifest_digest=manifest.manifest_digest,
        )
    except OSError as exc:
        raise BackupTransferError("Backup attempt could not be transferred completely.") from exc
    finally:
        discard_attempt(workspace)


def _capture_attempt(source_database: Path, attempt_root: Path) -> BackupManifest:
    paths = GenerationPaths(attempt_root)
    staged = attempt_root / f"{_STAGING_PREFIX}database-{uuid.uuid4().hex}.tmp"
    warnings: list[str] = []
    try:
        connection = _connect_builder(staged)
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup staging database could not be created.") from exc
    try:
        info = _snapshot_into(connection, source_database)
        _transfer_objects(source_database, connection, paths)
        entries = _referenced_object_entries(connection)
        _validate_snapshot(connection, paths)
    finally:
        connection.close()
    database_entry = _publish_staged_database(staged, paths, warnings)
    return _write_manifest(attempt_root, info, (database_entry, *entries), warnings)


def restore_backup(backup_root: Path, destination: Path) -> RestoreResult:
    """Copy one backup into a fresh root and verify it before reporting success.

    The original generation is never opened. Verification covers every recorded
    digest, ``PRAGMA integrity_check``, ``PRAGMA foreign_key_check``, the
    repository application invariants, and the manifest generation identity.

    Args:
        backup_root: A backup container or a direct version-1 backup directory.
        destination: Fresh restore root. It must not exist, or be an empty
            private directory, and must be separate from ``backup_root``.

    Returns:
        A receipt describing the verified restored copy.

    Raises:
        BackupIncompleteError: If the backup has no complete manifest.
        BackupVerificationError: If any digest or database check fails.
        RepositoryPathError: If the destination is unsafe or already populated.
    """
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    with managed_read_lease(backup_root):
        return _restore_backup_unlocked(backup_root, destination)


def _restore_backup_unlocked(backup_root: Path, destination: Path) -> RestoreResult:
    input_root = _absolute_root(backup_root)
    source_root, manifest, _ = resolve_backup_input(input_root)
    verify_payload(source_root, manifest)
    target_root, created_root = _prepare_restore_root(destination, input_root)
    target_paths = GenerationPaths(target_root)
    warnings: list[str] = []
    try:
        _restore_database(source_root, manifest, target_paths, warnings)
        _restore_objects(source_root, manifest, target_paths)
        _verify_restored_database(manifest, target_paths)
        _restore_manifest_document(source_root, manifest, target_root, warnings)
        verify_payload(target_root, manifest)
        fsync_attempt_tree(target_root)
    except Exception:
        _rollback_restore(target_root, created_root=created_root)
        raise
    return RestoreResult(
        backup_root=input_root,
        destination=target_root,
        database=target_paths.database,
        source_generation=manifest.source_generation,
        dataset_revision=manifest.dataset_revision,
        file_count=len(manifest.files),
        byte_count=manifest.byte_count,
        manifest_digest=manifest.manifest_digest,
        warnings=tuple(warnings),
    )


def read_backup_manifest(backup_root: Path) -> BackupManifest:
    """Read a strict version-1 receipt from a direct backup or selected attempt."""
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    with managed_read_lease(backup_root):
        return resolve_backup_input(backup_root)[1]


def backup_status(backup_root: Path) -> BackupStatus:
    """Verify the selected receipt and exact payload, returning static failure reasons."""
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    with managed_read_lease(backup_root):
        return _backup_status_unlocked(backup_root)


def _backup_status_unlocked(backup_root: Path) -> BackupStatus:
    root = backup_root.expanduser().absolute()
    manifest = None
    try:
        _absolute_root(root)
        if not root.is_dir():
            return BackupStatus(root, False, "missing_backup_root", None)
        if not (root / MANIFEST_FILENAME).exists() and not (root / "backup-current.json").exists():
            reason = "missing_pointer" if (root / "attempts").exists() else "missing_manifest"
            return BackupStatus(root, False, reason, None)
        payload_root, manifest, _ = resolve_backup_input(root)
        verify_payload(payload_root, manifest)
    except RepositoryBackupError as exc:
        return BackupStatus(root, False, exc.reason, manifest)
    except (OSError, RepositoryPathError):
        return BackupStatus(root, False, "incomplete_backup", manifest)
    return BackupStatus(root, True, "complete", manifest)


def _snapshot_into(connection: sqlite3.Connection, source_database: Path) -> RepositoryInfo:
    """Copy committed source state into the staging database and identify it."""
    source = _connect_readonly(source_database)
    try:
        source.backup(connection)
    except sqlite3.Error as exc:
        raise BackupTransferError(
            "SQLite online backup could not transfer the generation snapshot. "
            "Retry once the active writer is quiesced.",
        ) from exc
    finally:
        source.close()
    _normalize_journal_mode(connection)
    return _read_info(
        connection,
        expected_schema_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
    )


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
        raise BackupTransferError("SQLite file could not be opened for backup.") from exc
    return connection


def _transfer_objects(
    source_database: Path,
    connection: sqlite3.Connection,
    destination_paths: GenerationPaths,
) -> None:
    """Verify and carry every referenced immutable object into the backup."""
    try:
        SourceObjectStore(destination_paths).prepare()
        _copy_source_objects(source_database, connection, destination_paths)
    except OSError as exc:
        raise BackupTransferError("Backup source objects could not be transferred.") from exc
    except (ObjectStoreError, RepositoryIntegrityError, RepositoryPathError) as exc:
        raise BackupTransferError(
            "A referenced immutable source object could not be backed up.",
        ) from exc


def _referenced_object_entries(connection: sqlite3.Connection) -> tuple[BackupFileEntry, ...]:
    """Return manifest entries for every object the snapshot references."""
    rows = connection.execute(
        "SELECT source_artifact_id, byte_length, object_path FROM source_artifacts "
        "ORDER BY source_artifact_id",
    ).fetchall()
    return tuple(
        BackupFileEntry(
            path=str(row[2]),
            sha256=str(row[0]),
            byte_length=int(row[1]),
        )
        for row in rows
    )


def _validate_snapshot(connection: sqlite3.Connection, paths: GenerationPaths) -> None:
    """Prove the snapshot is a valid repository before any manifest is written."""
    try:
        info = _validate_connection(
            connection,
            object_paths=paths,
            expected_schema_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
        )
    except (RepositoryIntegrityError, RepositoryVersionError) as exc:
        raise BackupVerificationError(
            "The captured snapshot failed repository validation; no backup was committed.",
        ) from exc
    if info.dataset_generation is None:
        raise BackupVerificationError("The captured snapshot has no generation identity.")


def _publish_staged_database(
    staged: Path,
    paths: GenerationPaths,
    warnings: list[str],
) -> BackupFileEntry:
    """Hash, fsync, and atomically publish the staged snapshot database."""
    if Path(f"{staged}-wal").exists() or Path(f"{staged}-journal").exists():
        raise BackupTransferError("Backup snapshot retained an unmerged SQLite sidecar.")
    entry = _publish_staged_file(staged, paths.database, paths.root, warnings)
    if entry.path != DATABASE_BASENAME:
        raise BackupTransferError("Backup snapshot could not be published at its fixed path.")
    return entry


def _publish_staged_file(
    staged: Path,
    final: Path,
    root: Path,
    warnings: list[str],
) -> BackupFileEntry:
    """Publish one staged payload file atomically and record its digest."""
    byte_length, digest = _hash_regular_file(staged)
    try:
        _fsync_file(staged)
        os.replace(staged, final)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Backup payload could not be published atomically.") from exc
    _record_directory_fsync(final.parent, warnings)
    relative = final.relative_to(root).as_posix()
    return BackupFileEntry(path=relative, sha256=f"sha256:{digest}", byte_length=byte_length)


def _record_directory_fsync(directory: Path, warnings: list[str]) -> None:
    """Require directory durability before returning a successful receipt."""
    try:
        _assert_no_symlink_ancestors(directory)
        _fsync_directory(directory)
    except OSError as exc:
        raise BackupTransferError("Backup directory durability could not be confirmed.") from exc


def _write_manifest(
    backup_root: Path,
    info: RepositoryInfo,
    entries: tuple[BackupFileEntry, ...],
    warnings: list[str],
) -> BackupManifest:
    """Finish the local receipt inside this call's unpublished attempt directory."""
    manifest = _completed_manifest(info, entries)
    staged = backup_root / f"{_STAGING_PREFIX}manifest-{uuid.uuid4().hex}.tmp"
    document = {**manifest.to_payload(), "manifest_digest": manifest.manifest_digest}
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        _write_private_file(staged, payload.encode("utf-8"))
        os.replace(staged, backup_root / MANIFEST_FILENAME)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Backup completion manifest could not be published.") from exc
    _record_directory_fsync(backup_root, warnings)
    return manifest


def _completed_manifest(
    info: RepositoryInfo,
    entries: tuple[BackupFileEntry, ...],
) -> BackupManifest:
    """Build the self-digested manifest document for one verified backup."""
    generation = info.dataset_generation
    revision = info.dataset_revision
    if generation is None or revision is None:
        raise RepositoryBackupError("Backup source generation identity is incomplete.")
    ordered = tuple(sorted(entries, key=lambda entry: entry.path))
    manifest = BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        kind=BACKUP_KIND,
        backup_id=uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_generation=generation,
        dataset_revision=revision,
        files=ordered,
        manifest_digest="",
    )
    return replace(manifest, manifest_digest=_digest_text(_canonical_json(manifest.to_payload())))


def _restore_database(
    source_root: Path,
    manifest: BackupManifest,
    target_paths: GenerationPaths,
    warnings: list[str],
) -> None:
    """Copy the snapshot into the restore root and prove its digest."""
    entry = manifest.entry(DATABASE_BASENAME)
    staged = target_paths.root / f"{_STAGING_PREFIX}restore-{uuid.uuid4().hex}.tmp"
    byte_length, digest = _copy_regular_file(source_root / DATABASE_BASENAME, staged)
    if byte_length != entry.byte_length or f"sha256:{digest}" != entry.sha256:
        staged.unlink(missing_ok=True)
        raise BackupVerificationError("Restored database does not match its recorded digest.")
    _publish_staged_file(staged, target_paths.database, target_paths.root, warnings)


def _restore_objects(
    source_root: Path,
    manifest: BackupManifest,
    target_paths: GenerationPaths,
) -> None:
    """Re-publish every backed-up source object and prove its identity."""
    store = SourceObjectStore(target_paths)
    for entry in manifest.files:
        if entry.role != _OBJECT_ROLE:
            continue
        published = _publish_backed_up_object(store, source_root / entry.path)
        if (
            published.digest_hex != entry.sha256.removeprefix("sha256:")
            or published.byte_length != entry.byte_length
            or published.relative_path != entry.path
        ):
            raise BackupVerificationError("A restored source object does not match the manifest.")


def _publish_backed_up_object(store: SourceObjectStore, source: Path) -> SourceArtifact:
    """Publish one backed-up object, reporting transfer and corruption separately."""
    try:
        return store.publish_path(source)
    except ObjectCorruptionError as exc:
        raise BackupVerificationError("A restored source object failed its digest check.") from exc
    except OSError as exc:
        raise BackupTransferError("Backup source objects could not be restored.") from exc
    except (ObjectStoreError, RepositoryPathError) as exc:
        raise BackupTransferError("A restored source object could not be published.") from exc


def _verify_restored_database(
    manifest: BackupManifest,
    target_paths: GenerationPaths,
) -> RepositoryInfo:
    """Run integrity, foreign-key, and identity checks on the restored copy."""
    connection = _connect_readonly(target_paths.database)
    try:
        info = _validate_connection(
            connection,
            object_paths=target_paths,
            expected_schema_version=int(connection.execute("PRAGMA user_version").fetchone()[0]),
        )
    except (RepositoryIntegrityError, RepositoryVersionError) as exc:
        raise BackupVerificationError("Restored database failed repository validation.") from exc
    finally:
        connection.close()
    if info.dataset_generation != manifest.source_generation:
        raise BackupVerificationError("Restored generation disagrees with the backup manifest.")
    if info.dataset_revision != manifest.dataset_revision:
        raise BackupVerificationError("Restored revision disagrees with the backup manifest.")
    return info


def _restore_manifest_document(
    source_root: Path,
    manifest: BackupManifest,
    target_root: Path,
    warnings: list[str],
) -> None:
    """Carry the verified completion manifest into the restored root."""
    try:
        raw = read_regular_bytes(source_root / MANIFEST_FILENAME)
    except OSError as exc:
        raise BackupIncompleteError("Backup completion manifest disappeared.") from exc
    if verify_manifest_bytes(raw) != manifest:
        raise BackupVerificationError("Backup manifest bytes changed during restore.")
    staged = target_root / f"{_STAGING_PREFIX}manifest-{uuid.uuid4().hex}.tmp"
    try:
        _write_private_file(staged, raw)
        os.replace(staged, target_root / MANIFEST_FILENAME)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Restored completion manifest could not be published.") from exc
    _record_directory_fsync(target_root, warnings)


def _rollback_restore(target_root: Path, *, created_root: bool) -> None:
    """Remove every restored file so a failed restore leaves no usable copy."""
    if created_root:
        shutil.rmtree(target_root, ignore_errors=True)
        return
    for child in target_root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _prepare_restore_root(destination: Path, source_root: Path) -> tuple[Path, bool]:
    """Return a fresh private restore root and whether this call created it."""
    root = _absolute_root(destination)
    _reject_overlapping_roots(root, source_root)
    created_root = not root.exists()
    if not created_root:
        _require_empty_directory(root)
    try:
        _mkdir_checked(root)
    except ObjectStoreError as exc:
        raise BackupTransferError("Restore destination durability could not be confirmed.") from exc
    except OSError as exc:
        raise RepositoryPathError("Restore destination root could not be prepared.") from exc
    return root, created_root


def _require_empty_directory(root: Path) -> None:
    """Reject a restore destination that already holds entries."""
    if not root.is_dir():
        raise RepositoryPathError("Restore destination must be a directory.")
    if next(root.iterdir(), None) is not None:
        raise RepositoryPathError("Restore destination must be empty.")


def _reject_overlapping_roots(root: Path, other: Path) -> None:
    """Refuse to nest a backup root and a generation root inside each other."""
    if root == other or root.is_relative_to(other) or other.is_relative_to(root):
        raise RepositoryPathError("Backup and restore roots must be separate directory trees.")


def _absolute_root(path: Path) -> Path:
    """Return an absolute, symlink-free view of one operator-supplied root."""
    root = path.expanduser().absolute()
    _assert_no_symlink_ancestors(root, allow_missing=True)
    return root.resolve(strict=False)


def _copy_regular_file(source: Path, staged: Path) -> tuple[int, str]:
    try:
        return copy_regular_file(source, staged)
    except RepositoryBackupError as exc:
        raise BackupTransferError("Backup payload could not be transferred safely.") from exc


def _hash_regular_file(path: Path) -> tuple[int, str]:
    return fingerprint_regular_file(path)


def _write_private_file(path: Path, data: bytes) -> None:
    """Create one private regular file with the given bytes."""
    _assert_no_symlink_ancestors(path, allow_missing=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(descriptor, data)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    """Flush a regular file without following a link or waiting on a special file."""
    _assert_no_symlink_ancestors(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BackupTransferError("Backup payload must be a regular file.")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest_from_bytes(raw: bytes) -> BackupManifest:
    return verify_manifest_bytes(raw)


def _canonical_json(payload: Any) -> bytes:
    """Return canonical JSON bytes used for every backup digest."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8",
    )


def _digest_text(data: bytes) -> str:
    """Return the ``sha256:`` prefixed digest of raw bytes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


__all__ = [
    "BACKUP_KIND",
    "BACKUP_SCHEMA_VERSION",
    "DATABASE_BASENAME",
    "MANIFEST_FILENAME",
    "RESTORE_CHECKS",
    "BackupFileEntry",
    "BackupManifest",
    "BackupResult",
    "BackupStatus",
    "RestoreResult",
    "backup_status",
    "create_backup",
    "read_backup_manifest",
    "resolve_generation_database",
    "restore_backup",
]
