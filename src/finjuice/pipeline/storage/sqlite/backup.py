"""Atomic, verifiable backups of one published authoritative SQLite generation.

One backup is a single self-describing directory holding:

* ``finjuice.sqlite3`` — a consistent snapshot taken with the SQLite Online
  Backup API (:meth:`sqlite3.Connection.backup`) so a writer may stay active
  while the snapshot is captured;
* ``objects/sha256/...`` — every immutable source object the snapshot
  references, copied through :class:`SourceObjectStore` so content addressing
  and read-only permissions survive the round trip;
* ``backup-manifest.json`` — the completion marker, written last through a
  temporary file plus :func:`os.replace`.

The manifest is the only completion evidence. A backup whose manifest is
missing, unreadable, or structurally invalid is reported as incomplete and
never as a success. A transfer failure raises before the new manifest is
swapped in, so any previous complete manifest in the destination stays
intact, and publishing prunes payload files the new manifest does not list
so a complete manifest always describes the exact payload set.
:func:`backup_status` re-verifies every listed payload file (existence,
size, and SHA-256) before reporting a backup complete.

:meth:`restore_backup` never opens or writes the original generation: it copies
the backup into a fresh private root and verifies digests, ``PRAGMA
integrity_check``, ``PRAGMA foreign_key_check``, and the repository application
invariants before the copy is reported usable. A failed verification removes
everything the restore created.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Final

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
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import (
    SourceArtifact,
    SourceObjectStore,
    _assert_no_symlink_ancestors,
    _mkdir_checked,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import (
    RepositoryInfo,
    _cleanup_staging,
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
_CHUNK_SIZE: Final = 1024 * 1024
_BUSY_TIMEOUT_MS: Final = 5_000
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
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
    """Back up one published generation through the SQLite Online Backup API.

    The snapshot, every immutable source object it references, and a completion
    manifest are published into ``destination_root``. Re-running against an
    unchanged generation rewrites identical payload bytes and publishes a new
    manifest, so a repeated backup is idempotent. Payload files the new
    manifest does not list (orphans of an earlier failed backup) are pruned
    before the manifest is published. The new manifest replaces any previous
    completion manifest as the final atomic step, so a failure at any earlier
    point leaves the previous complete backup untouched.

    Args:
        database: Path to the published ``finjuice.sqlite3`` (or its generation
            root).
        destination_root: Backup directory to publish into. It is created as a
            private directory when missing and must live outside the source
            generation.

    Returns:
        A receipt describing the completed backup.

    Raises:
        RepositoryBackupError: If the source generation is missing, the backup
            could not be transferred, or the snapshot failed verification. No
            new manifest is published in any of those cases, and a previous
            complete manifest in the destination stays intact.
    """
    source_database = resolve_generation_database(database)
    source_root = GenerationPaths(source_database.parent).root
    backup_root = _prepare_backup_root(destination_root, source_root)
    destination_paths = GenerationPaths(backup_root)
    warnings: list[str] = []
    staged = backup_root / f"{_STAGING_PREFIX}database-{uuid.uuid4().hex}.tmp"
    try:
        connection = _connect_builder(staged)
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup staging database could not be created.") from exc
    try:
        info = _snapshot_into(connection, source_database)
        _transfer_objects(source_database, connection, destination_paths)
        entries = _referenced_object_entries(connection)
        _validate_snapshot(connection, destination_paths)
    except Exception:
        connection.close()
        _cleanup_staging(staged)
        raise
    connection.close()
    _prune_unlisted_payload(backup_root, entries)
    database_entry = _publish_staged_database(staged, destination_paths, warnings)
    manifest = _write_manifest(backup_root, info, (database_entry, *entries), warnings)
    return BackupResult(
        backup_root=backup_root,
        manifest_path=backup_root / MANIFEST_FILENAME,
        backup_id=manifest.backup_id,
        source_generation=manifest.source_generation,
        dataset_revision=manifest.dataset_revision,
        file_count=len(manifest.files),
        byte_count=manifest.byte_count,
        database_digest=database_entry.sha256,
        manifest_digest=manifest.manifest_digest,
        warnings=tuple(warnings),
    )


def restore_backup(backup_root: Path, destination: Path) -> RestoreResult:
    """Copy one backup into a fresh root and verify it before reporting success.

    The original generation is never opened. Verification covers every recorded
    digest, ``PRAGMA integrity_check``, ``PRAGMA foreign_key_check``, the
    repository application invariants, and the manifest generation identity.

    Args:
        backup_root: Directory holding a complete backup.
        destination: Fresh restore root. It must not exist, or be an empty
            private directory, and must be separate from ``backup_root``.

    Returns:
        A receipt describing the verified restored copy.

    Raises:
        BackupIncompleteError: If the backup has no complete manifest.
        BackupVerificationError: If any digest or database check fails.
        RepositoryPathError: If the destination is unsafe or already populated.
    """
    source_root = _existing_backup_root(backup_root)
    manifest = read_backup_manifest(source_root)
    target_root, created_root = _prepare_restore_root(destination, source_root)
    target_paths = GenerationPaths(target_root)
    warnings: list[str] = []
    try:
        _reject_unlisted_payload(source_root, manifest)
        _restore_database(source_root, manifest, target_paths, warnings)
        _restore_objects(source_root, manifest, target_paths)
        _verify_restored_database(manifest, target_paths)
        _restore_manifest_document(source_root, manifest, target_root, warnings)
    except Exception:
        _rollback_restore(target_root, created_root=created_root)
        raise
    return RestoreResult(
        backup_root=source_root,
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
    """Parse and self-verify one backup completion manifest.

    Args:
        backup_root: Directory holding ``backup-manifest.json``.

    Returns:
        The verified manifest.

    Raises:
        BackupIncompleteError: If the manifest is missing, unreadable, or
            structurally invalid, which always means the backup is incomplete.
        BackupVerificationError: If the manifest does not match its own digest.
    """
    root = _absolute_root(backup_root)
    try:
        raw = (root / MANIFEST_FILENAME).read_bytes()
    except OSError as exc:
        raise BackupIncompleteError(
            "Backup completion manifest could not be read; the backup is incomplete.",
        ) from exc
    return _manifest_from_bytes(raw)


def backup_status(backup_root: Path) -> BackupStatus:
    """Report whether one backup directory holds a complete, trusted backup.

    A parsed manifest alone is not trusted: every listed payload file is
    re-verified for existence, recorded size, and SHA-256 digest, and any
    mismatch is reported as not-complete with a stable reason.

    This never raises for an unusable backup: an incomplete backup is reported
    with ``complete=False`` and a stable machine-readable reason.

    Args:
        backup_root: Directory to inspect.

    Returns:
        The completeness verdict plus the manifest when the backup is complete.
    """
    root = _absolute_root(backup_root)
    if not root.is_dir():
        return BackupStatus(root, False, "missing_backup_root", None)
    if not (root / MANIFEST_FILENAME).is_file():
        return BackupStatus(root, False, "missing_manifest", None)
    try:
        manifest = read_backup_manifest(root)
    except RepositoryBackupError as exc:
        return BackupStatus(root, False, exc.reason, None)
    defect = _payload_defect_reason(root, manifest)
    if defect is not None:
        return BackupStatus(root, False, defect, manifest)
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
    return _read_info(connection)


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
        info = _validate_connection(connection, object_paths=paths)
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
    """Flush one directory after a successful replace, recording any failure.

    The publish itself already succeeded through :func:`os.replace`; a
    directory fsync failure must not turn that success into a reported
    failure, so it is recorded as a warning on the result payload instead.
    """
    try:
        _fsync_directory(directory)
    except OSError:
        warnings.append("directory_fsync_failed")


def _write_manifest(
    backup_root: Path,
    info: RepositoryInfo,
    entries: tuple[BackupFileEntry, ...],
    warnings: list[str],
) -> BackupManifest:
    """Atomically swap in the completion manifest for a proven backup.

    This is the final commit step of :func:`create_backup`: the staged
    manifest replaces any previous completion manifest through
    :func:`os.replace`, so any failure before this point leaves the previous
    complete backup untouched.
    """
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


def _prune_unlisted_payload(backup_root: Path, entries: tuple[BackupFileEntry, ...]) -> None:
    """Remove destination payload files the new manifest does not list.

    Orphans left behind by an earlier failed backup would otherwise poison
    the destination permanently: :func:`restore_backup` rejects any backup
    directory holding payload outside its manifest, so pruning guarantees a
    complete manifest describes the exact payload set. The fixed snapshot
    path is always preserved so the previous database survives until it is
    atomically replaced moments before the manifest swap.
    """
    listed = {entry.path for entry in entries} | {DATABASE_BASENAME, MANIFEST_FILENAME}
    for path in _inventoried_payload(backup_root):
        relative = path.relative_to(backup_root).as_posix()
        if path.name.startswith(_STAGING_PREFIX):
            continue  # the staging snapshot of this very backup is mid-publish
        if relative in listed or _entry_kind(path) == "directory":
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise BackupTransferError("Unlisted backup payload could not be pruned.") from exc


def _payload_defect_reason(root: Path, manifest: BackupManifest) -> str | None:
    """Return why listed payload disagrees with the manifest, or ``None``."""
    for entry in manifest.files:
        try:
            byte_length, digest = _hash_regular_file(root / entry.path)
        except BackupTransferError:
            return "payload_missing"
        if byte_length != entry.byte_length:
            return "payload_size_mismatch"
        if f"sha256:{digest}" != entry.sha256:
            return "payload_digest_mismatch"
    return None


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
        info = _validate_connection(connection, object_paths=target_paths)
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
        raw = (source_root / MANIFEST_FILENAME).read_bytes()
    except OSError as exc:
        raise BackupIncompleteError("Backup completion manifest disappeared.") from exc
    payload = _manifest_payload_from_bytes(raw)
    digest_payload = {k: v for k, v in payload.items() if k != "manifest_digest"}
    if _digest_text(_canonical_json(digest_payload)) != manifest.manifest_digest:
        raise BackupVerificationError("Backup manifest bytes changed during restore.")
    staged = target_root / f"{_STAGING_PREFIX}manifest-{uuid.uuid4().hex}.tmp"
    try:
        _write_private_file(staged, raw)
        os.replace(staged, target_root / MANIFEST_FILENAME)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Restored completion manifest could not be published.") from exc
    _record_directory_fsync(target_root, warnings)


def _reject_unlisted_payload(source_root: Path, manifest: BackupManifest) -> None:
    """Refuse a backup directory holding payload outside its manifest."""
    listed = {entry.path for entry in manifest.files} | {MANIFEST_FILENAME}
    for path in _inventoried_payload(source_root):
        relative = path.relative_to(source_root).as_posix()
        kind = _entry_kind(path)
        if kind == "directory":
            continue
        if kind != "file" or relative not in listed:
            raise BackupVerificationError("Backup directory holds payload outside its manifest.")


def _inventoried_payload(source_root: Path) -> list[Path]:
    """Return every entry below one backup root in a stable order."""
    try:
        return sorted(source_root.rglob("*"))
    except OSError as exc:
        raise BackupVerificationError("Backup directory could not be inventoried.") from exc


def _entry_kind(path: Path) -> str:
    """Classify one backup entry without following symlinks."""
    try:
        entry = path.lstat()
    except OSError as exc:
        raise BackupVerificationError("Backup payload could not be inspected.") from exc
    if stat.S_ISDIR(entry.st_mode):
        return "directory"
    if stat.S_ISREG(entry.st_mode):
        return "file"
    return "other"


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


def _prepare_backup_root(destination_root: Path, source_root: Path) -> Path:
    """Create or reuse a private backup root that is separate from the source."""
    root = _absolute_root(destination_root)
    _reject_overlapping_roots(root, source_root)
    try:
        _mkdir_checked(root)
    except OSError as exc:
        raise RepositoryPathError("Backup destination root could not be prepared.") from exc
    _clear_stale_staging(root)
    return root


def _prepare_restore_root(destination: Path, source_root: Path) -> tuple[Path, bool]:
    """Return a fresh private restore root and whether this call created it."""
    root = _absolute_root(destination)
    _reject_overlapping_roots(root, source_root)
    created_root = not root.exists()
    if not created_root:
        _require_empty_directory(root)
    try:
        _mkdir_checked(root)
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


def _existing_backup_root(backup_root: Path) -> Path:
    """Return an existing backup directory without following symlinks."""
    root = _absolute_root(backup_root)
    if not root.is_dir():
        raise BackupIncompleteError("Backup directory is missing; the backup is incomplete.")
    return root


def _absolute_root(path: Path) -> Path:
    """Return an absolute, symlink-free view of one operator-supplied root."""
    root = path.expanduser().absolute()
    _assert_no_symlink_ancestors(root, allow_missing=True)
    return root


def _clear_stale_staging(backup_root: Path) -> None:
    """Remove staging files left behind by an earlier failed backup."""
    try:
        for staged in backup_root.glob(f"{_STAGING_PREFIX}*.tmp"):
            staged.unlink(missing_ok=True)
    except OSError as exc:
        raise BackupTransferError("Stale backup staging files could not be removed.") from exc


def _copy_regular_file(source: Path, staged: Path) -> tuple[int, str]:
    """Stream one regular file into a private staged path and digest it."""
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with source.open("rb") as reader:
            descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                while True:
                    chunk = reader.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    byte_length += len(chunk)
                    digest.update(chunk)
                    os.write(descriptor, chunk)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Backup payload could not be copied.") from exc
    return byte_length, digest.hexdigest()


def _hash_regular_file(path: Path) -> tuple[int, str]:
    """Return the size and SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    byte_length = 0
    try:
        with path.open("rb") as reader:
            while True:
                chunk = reader.read(_CHUNK_SIZE)
                if not chunk:
                    break
                byte_length += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise BackupTransferError("Backup payload could not be hashed.") from exc
    return byte_length, digest.hexdigest()


def _write_private_file(path: Path, data: bytes) -> None:
    """Create one private regular file with the given bytes."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    """Flush one file's bytes to stable storage."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest_payload_from_bytes(raw: bytes) -> dict[str, Any]:
    """Decode raw manifest bytes into their JSON payload object."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupIncompleteError(
            "Backup completion manifest is not readable JSON; the backup is incomplete.",
        ) from exc
    if not isinstance(payload, dict):
        raise BackupIncompleteError("Backup completion manifest must be a JSON object.")
    return payload


def _manifest_from_bytes(raw: bytes) -> BackupManifest:
    """Decode and structurally validate manifest bytes."""
    manifest = _manifest_from_payload(_manifest_payload_from_bytes(raw))
    if _digest_text(_canonical_json(manifest.to_payload())) != manifest.manifest_digest:
        raise BackupVerificationError("Backup completion manifest does not match its own digest.")
    return manifest


def _manifest_from_payload(payload: dict[str, Any]) -> BackupManifest:
    """Build a manifest from validated payload fields."""
    manifest = BackupManifest(
        schema_version=_manifest_int(payload, "schema_version"),
        kind=_manifest_text(payload, "kind"),
        backup_id=_manifest_text(payload, "backup_id"),
        created_at=_manifest_text(payload, "created_at"),
        source_generation=_manifest_generation(payload),
        dataset_revision=_manifest_int(payload, "dataset_revision"),
        files=_manifest_files(payload.get("files")),
        manifest_digest=_manifest_digest_text(payload),
    )
    if manifest.schema_version != BACKUP_SCHEMA_VERSION or manifest.kind != BACKUP_KIND:
        raise BackupIncompleteError("Backup was written by an unsupported backup format.")
    return manifest


def _manifest_files(raw: Any) -> tuple[BackupFileEntry, ...]:
    """Validate the recorded payload list of one manifest."""
    if not isinstance(raw, list) or not raw:
        raise BackupIncompleteError("Backup manifest must list at least one payload file.")
    entries = tuple(_manifest_file_entry(item) for item in raw)
    if sum(1 for entry in entries if entry.role == _DATABASE_ROLE) != 1:
        raise BackupIncompleteError("Backup manifest must record exactly one database snapshot.")
    return entries


def _manifest_file_entry(raw: Any) -> BackupFileEntry:
    """Validate one recorded payload file entry."""
    if not isinstance(raw, dict):
        raise BackupIncompleteError("Backup manifest file entries must be JSON objects.")
    path = _manifest_relative_path(_manifest_text(raw, "path"))
    sha256 = _manifest_text(raw, "sha256")
    byte_length = _manifest_int(raw, "byte_length")
    if _DIGEST_RE.fullmatch(sha256) is None or byte_length < 0:
        raise BackupIncompleteError("Backup manifest records an invalid payload digest or size.")
    return BackupFileEntry(path=path, sha256=sha256, byte_length=byte_length)


def _manifest_relative_path(raw: str) -> str:
    """Reject absolute, escaping, or out-of-contract payload paths."""
    path = PurePosixPath(raw)
    if (
        raw in {"", ".", MANIFEST_FILENAME}
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in raw
    ):
        raise BackupIncompleteError("Backup manifest records an unsafe payload path.")
    if raw != DATABASE_BASENAME and path.parts[0] != OBJECT_NAMESPACE:
        raise BackupIncompleteError("Backup manifest records a payload path outside the contract.")
    return raw


def _manifest_text(payload: dict[str, Any], key: str) -> str:
    """Return one required non-empty manifest string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BackupIncompleteError(f"Backup manifest field '{key}' must be a non-empty string.")
    return value


def _manifest_int(payload: dict[str, Any], key: str) -> int:
    """Return one required non-negative manifest integer field."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BackupIncompleteError(f"Backup manifest field '{key}' must be a whole number.")
    return value


def _manifest_generation(payload: dict[str, Any]) -> str:
    """Return the recorded source generation identity."""
    raw = _manifest_text(payload, "source_generation")
    try:
        return validate_entity_id(raw)
    except ValueError as exc:
        raise BackupIncompleteError("Backup manifest records an invalid generation ID.") from exc


def _manifest_digest_text(payload: dict[str, Any]) -> str:
    """Return the recorded manifest self-digest."""
    digest = _manifest_text(payload, "manifest_digest")
    if _DIGEST_RE.fullmatch(digest) is None:
        raise BackupIncompleteError("Backup manifest records an invalid manifest digest.")
    return digest


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
