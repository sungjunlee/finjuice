"""Atomic, verifiable backups of one published authoritative SQLite generation.

Each completed backup is an immutable attempt directory:

* ``attempts/<backup_id>/finjuice.sqlite3`` — a consistent snapshot taken with the
  SQLite Online Backup API (:meth:`sqlite3.Connection.backup`);
* ``attempts/<backup_id>/objects/sha256/...`` — every immutable source object,
  config revision artifact, and release evidence the snapshot references;
* ``attempts/<backup_id>/backup-manifest.json`` — the attempt completion marker;
* ``CURRENT`` — a pointer file naming the current attempt, replaced last.

The manifest is the only completion evidence for one attempt. A backup whose
manifest is missing, unreadable, or structurally invalid is reported as
incomplete and never as a success. A late DB or manifest failure leaves any
previous complete attempt untouched; survival of a previous manifest file
alone is not treated as preservation of the previous payload.
:func:`backup_status` and :func:`restore_backup` share the same strict
verification (known fields, unique regular files, listed-payload closure).

:meth:`restore_backup` never opens or writes the original generation: it copies
the current complete attempt into a fresh private root and verifies digests,
``PRAGMA integrity_check``, ``PRAGMA foreign_key_check``, and the repository
application invariants before the copy is reported usable. A failed
verification removes everything the restore created.
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
CURRENT_FILENAME: Final = "CURRENT"
ATTEMPTS_NAMESPACE: Final = "attempts"
ACTIVATION_ABSENT: Final = "intentionally_absent"

_STAGING_PREFIX: Final = ".finjuice-backup-"
_CHUNK_SIZE: Final = 1024 * 1024
_BUSY_TIMEOUT_MS: Final = 5_000
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_RE: Final = re.compile(rf"^{ATTEMPTS_NAMESPACE}/[0-9a-f]{{32}}$")
_DATABASE_ROLE: Final = "database"
_OBJECT_ROLE: Final = "object"
_MANIFEST_KEYS: Final = frozenset(
    {
        "activation_binding",
        "backup_id",
        "config_revisions",
        "created_at",
        "dataset_revision",
        "files",
        "kind",
        "manifest_digest",
        "release",
        "schema_version",
        "source_generation",
    }
)
_FILE_ENTRY_KEYS: Final = frozenset({"byte_length", "path", "sha256"})
_RELEASE_KEYS: Final = frozenset(
    {"application_id", "finjuice_version", "schema_version"},
)
_CONFIG_REVISION_KEYS: Final = frozenset(
    {"config_kind", "revision_id", "source_artifact_id"},
)

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
    release: dict[str, Any] | None = None
    config_revisions: tuple[dict[str, Any], ...] | None = None
    activation_binding: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical payload covered by :attr:`manifest_digest`."""
        payload: dict[str, Any] = {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "dataset_revision": self.dataset_revision,
            "files": [entry.to_payload() for entry in self.files],
            "kind": self.kind,
            "schema_version": self.schema_version,
            "source_generation": self.source_generation,
        }
        if self.activation_binding is not None:
            payload["activation_binding"] = self.activation_binding
        if self.config_revisions is not None:
            payload["config_revisions"] = list(self.config_revisions)
        if self.release is not None:
            payload["release"] = self.release
        return payload

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
    config_revision_count: int = 0
    activation_binding: str = ACTIVATION_ABSENT

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe CLI payload (no filesystem paths)."""
        return {
            "activation_binding": self.activation_binding,
            "backup_id": self.backup_id,
            "backup_kind": BACKUP_KIND,
            "byte_count": self.byte_count,
            "complete": self.complete,
            "config_revision_count": self.config_revision_count,
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
    generation_status: str = "inactive"

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe CLI payload (no filesystem paths)."""
        return {
            "byte_count": self.byte_count,
            "checks": list(self.checks),
            "dataset_revision": self.dataset_revision,
            "file_count": self.file_count,
            "generation_status": self.generation_status,
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

    The snapshot, every immutable source object and config/release artifact it
    references, and a completion manifest are published as a new immutable
    attempt. Referenced source objects are GC-pinned until that attempt's
    pointer is published. Re-running against an unchanged generation writes
    identical payload bytes into a new attempt and atomically retargets
    ``CURRENT``. A failure before the pointer swap leaves the previous complete
    attempt fully intact, including its database and objects.

    Direct v1 destinations (payload files at the backup root) can still be
    read and restored. Recreating into those roots is refused so the original
    bytes stay untouched.

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
            new current pointer is published in any of those cases.
    """
    source_database = resolve_generation_database(database)
    source_root = GenerationPaths(source_database.parent).root
    backup_root = _prepare_backup_root(destination_root, source_root)
    backup_id = uuid.uuid4().hex
    attempt_root = backup_root / ATTEMPTS_NAMESPACE / backup_id
    destination_paths = GenerationPaths(attempt_root)
    warnings: list[str] = []
    pins: _PinnedSources | None = None
    try:
        _mkdir_checked(attempt_root, boundary=backup_root)
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup attempt directory could not be prepared.") from exc
    staged = attempt_root / f"{_STAGING_PREFIX}database-{uuid.uuid4().hex}.tmp"
    try:
        connection = _connect_builder(staged)
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup staging database could not be created.") from exc
    try:
        info = _snapshot_into(connection, source_database)
        config_revisions = _collect_config_revisions(connection)
        release = _collect_release_evidence(info)
        pins = _pin_referenced_objects(source_database, connection, backup_root)
        _transfer_pinned_objects(pins, destination_paths)
        entries = _referenced_object_entries(connection)
        _assert_config_objects_collected(config_revisions, entries)
        _validate_snapshot(connection, destination_paths)
    except Exception:
        connection.close()
        _cleanup_staging(staged)
        if pins is not None:
            pins.release()
        raise
    connection.close()
    try:
        _prune_unlisted_payload(attempt_root, entries, warnings)
        database_entry = _publish_staged_database(staged, destination_paths, warnings)
        manifest = _write_manifest(
            attempt_root,
            info,
            (database_entry, *entries),
            backup_id=backup_id,
            release=release,
            config_revisions=config_revisions,
        )
        _publish_current_pointer(backup_root, backup_id, warnings)
    except Exception:
        if pins is not None:
            pins.release()
        raise
    assert pins is not None
    pins.release()
    return BackupResult(
        backup_root=backup_root,
        manifest_path=attempt_root / MANIFEST_FILENAME,
        backup_id=manifest.backup_id,
        source_generation=manifest.source_generation,
        dataset_revision=manifest.dataset_revision,
        file_count=len(manifest.files),
        byte_count=manifest.byte_count,
        database_digest=database_entry.sha256,
        manifest_digest=manifest.manifest_digest,
        warnings=tuple(warnings),
        config_revision_count=len(config_revisions),
        activation_binding=ACTIVATION_ABSENT,
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
    pointer_root = _existing_backup_root(backup_root)
    source_root = resolve_backup_payload_root(pointer_root)
    manifest = read_backup_manifest(pointer_root)
    target_root, created_root = _prepare_restore_root(destination, pointer_root)
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
        backup_root=pointer_root,
        destination=target_root,
        database=target_paths.database,
        source_generation=manifest.source_generation,
        dataset_revision=manifest.dataset_revision,
        file_count=len(manifest.files),
        byte_count=manifest.byte_count,
        manifest_digest=manifest.manifest_digest,
        warnings=tuple(warnings),
        generation_status="inactive",
    )


def read_backup_manifest(backup_root: Path) -> BackupManifest:
    """Parse and self-verify one backup completion manifest.

    Args:
        backup_root: Pointer root, current attempt directory, or a restored
            copy that still holds ``backup-manifest.json``.

    Returns:
        The verified manifest.

    Raises:
        BackupIncompleteError: If the manifest is missing, unreadable, or
            structurally invalid, which always means the backup is incomplete.
        BackupVerificationError: If the manifest does not match its own digest.
    """
    root = resolve_backup_payload_root(backup_root)
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
    re-verified for existence, recorded size, and SHA-256 digest, unlisted
    or non-regular payload is rejected, and any mismatch is reported as
    not-complete with a stable reason.

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
    try:
        payload_root = resolve_backup_payload_root(root)
    except RepositoryBackupError as exc:
        return BackupStatus(root, False, exc.reason, None)
    if not (payload_root / MANIFEST_FILENAME).is_file():
        return BackupStatus(root, False, "missing_manifest", None)
    try:
        manifest = read_backup_manifest(root)
        defect = _payload_defect_reason(payload_root, manifest)
    except RepositoryBackupError as exc:
        return BackupStatus(root, False, exc.reason, None)
    if defect is not None:
        return BackupStatus(root, False, defect, manifest)
    return BackupStatus(root, True, "complete", manifest)


def resolve_backup_payload_root(backup_root: Path) -> Path:
    """Return the attempt or direct-v1 directory that holds payload files.

    Args:
        backup_root: Operator-supplied backup root or an already-resolved
            attempt directory.

    Returns:
        The directory containing ``backup-manifest.json`` and payload files.

    Raises:
        BackupIncompleteError: If ``CURRENT`` is unreadable or names a missing
            attempt.
    """
    root = _absolute_root(backup_root)
    current = root / CURRENT_FILENAME
    if not current.exists():
        return root
    if _entry_kind(current) != "file":
        raise BackupIncompleteError("Backup current pointer is not a regular file.")
    try:
        relative = current.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BackupIncompleteError("Backup current pointer could not be read.") from exc
    if _ATTEMPT_RE.fullmatch(relative) is None:
        raise BackupIncompleteError("Backup current pointer does not name a trusted attempt.")
    payload = root / relative
    if not payload.is_dir() or payload.is_symlink():
        raise BackupIncompleteError("Backup current pointer does not name an attempt directory.")
    return payload


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


@dataclass
class _PinnedSources:
    """Hardlinked or copied source objects held until the backup pointer is durable."""

    pin_root: Path
    artifacts: tuple[tuple[Path, str, int], ...]

    def release(self) -> None:
        """Drop GC pins after the completion pointer is published or the attempt fails."""
        shutil.rmtree(self.pin_root, ignore_errors=True)


def _collect_config_revisions(connection: sqlite3.Connection) -> tuple[dict[str, Any], ...]:
    """Return snapshot config revisions without mixing in live YAML."""
    rows = connection.execute(
        "SELECT entity_id, config_kind, source_artifact_id FROM config_revisions "
        "ORDER BY entity_id",
    ).fetchall()
    return tuple(
        {
            "config_kind": str(row[1]),
            "revision_id": str(row[0]),
            "source_artifact_id": str(row[2]),
        }
        for row in rows
    )


def _collect_release_evidence(info: RepositoryInfo) -> dict[str, Any]:
    """Return snapshot schema identity plus the installed program version."""
    from finjuice import get_version

    return {
        "application_id": info.application_id,
        "finjuice_version": get_version(),
        "schema_version": info.schema_version,
    }


def _assert_config_objects_collected(
    config_revisions: tuple[dict[str, Any], ...],
    entries: tuple[BackupFileEntry, ...],
) -> None:
    """Refuse a backup that names a config artifact it did not collect."""
    collected = {entry.sha256 for entry in entries}
    for revision in config_revisions:
        if revision["source_artifact_id"] not in collected:
            raise BackupVerificationError(
                "A referenced config revision artifact was not collected into the backup.",
            )


def _pin_referenced_objects(
    source_database: Path,
    connection: sqlite3.Connection,
    backup_root: Path,
) -> _PinnedSources:
    """Hold referenced source inodes so GC cannot drop them during collection."""
    source_paths = GenerationPaths(source_database.parent)
    pin_root = backup_root / f"{_STAGING_PREFIX}pins-{uuid.uuid4().hex}"
    try:
        _mkdir_checked(pin_root, boundary=backup_root)
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup source pins could not be prepared.") from exc
    pinned: list[tuple[Path, str, int]] = []
    try:
        for entry in _referenced_object_entries(connection):
            source = source_paths.root / entry.path
            pin_path = pin_root / entry.sha256.removeprefix("sha256:")
            _pin_regular_file(source, pin_path)
            pinned.append((pin_path, entry.sha256, entry.byte_length))
    except Exception:
        shutil.rmtree(pin_root, ignore_errors=True)
        raise
    return _PinnedSources(pin_root=pin_root, artifacts=tuple(pinned))


def _pin_regular_file(source: Path, pin_path: Path) -> None:
    """Hold one source object by hardlink, falling back to a private copy."""
    try:
        os.link(source, pin_path, follow_symlinks=False)
        return
    except OSError:
        pass
    try:
        _copy_regular_file(source, pin_path)
    except BackupTransferError as exc:
        raise BackupTransferError(
            "A referenced immutable source object could not be pinned against GC.",
        ) from exc


def _transfer_pinned_objects(pins: _PinnedSources, destination_paths: GenerationPaths) -> None:
    """Publish GC-pinned source objects into the new attempt."""
    try:
        store = SourceObjectStore(destination_paths)
        store.prepare()
        for pin_path, artifact_id, byte_length in pins.artifacts:
            published = store.publish_path(pin_path)
            if published.artifact_id != artifact_id or published.byte_length != byte_length:
                raise BackupVerificationError(
                    "A referenced immutable source object changed while it was backed up.",
                )
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
    attempt_root: Path,
    info: RepositoryInfo,
    entries: tuple[BackupFileEntry, ...],
    *,
    backup_id: str,
    release: dict[str, Any],
    config_revisions: tuple[dict[str, Any], ...],
) -> BackupManifest:
    """Atomically publish the completion manifest for one isolated attempt.

    Directory fsync of the attempt is required before the current pointer may
    move. A failure here does not retarget ``CURRENT``, so the previous complete
    attempt stays fully intact.
    """
    manifest = _completed_manifest(
        info,
        entries,
        backup_id=backup_id,
        release=release,
        config_revisions=config_revisions,
    )
    staged = attempt_root / f"{_STAGING_PREFIX}manifest-{uuid.uuid4().hex}.tmp"
    document = {**manifest.to_payload(), "manifest_digest": manifest.manifest_digest}
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        _write_private_file(staged, payload.encode("utf-8"))
        os.replace(staged, attempt_root / MANIFEST_FILENAME)
        _fsync_directory(attempt_root)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Backup completion manifest could not be published.") from exc
    return manifest


def _publish_current_pointer(backup_root: Path, backup_id: str, warnings: list[str]) -> None:
    """Atomically retarget ``CURRENT`` after one attempt is durable."""
    relative = f"{ATTEMPTS_NAMESPACE}/{backup_id}"
    staged = backup_root / f"{_STAGING_PREFIX}current-{uuid.uuid4().hex}.tmp"
    try:
        _write_private_file(staged, f"{relative}\n".encode("utf-8"))
        os.replace(staged, backup_root / CURRENT_FILENAME)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise BackupTransferError("Backup current pointer could not be published.") from exc
    _record_directory_fsync(backup_root, warnings)


def _prune_unlisted_payload(
    backup_root: Path,
    entries: tuple[BackupFileEntry, ...],
    warnings: list[str],
) -> None:
    """Remove destination payload files the new manifest does not list.

    Kept for attempt-local cleanup of staging leftovers. It must never run
    against a previous complete attempt; previous preservation is proved by
    leaving that attempt directory intact, not by keeping a stale manifest
    file at the pointer root.
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
        warnings.append(f"pruned_orphan:{relative}")


def _payload_defect_reason(root: Path, manifest: BackupManifest) -> str | None:
    """Return why listed payload disagrees with the manifest, or ``None``."""
    listed = {entry.path for entry in manifest.files} | {MANIFEST_FILENAME}
    for path in _inventoried_payload(root):
        relative = path.relative_to(root).as_posix()
        kind = _entry_kind(path)
        if kind == "directory":
            continue
        if kind != "file" or relative not in listed:
            return "unlisted_payload" if relative not in listed else "payload_not_regular_file"
    for entry in manifest.files:
        target = root / entry.path
        try:
            kind = _entry_kind(target)
        except BackupVerificationError:
            return "payload_missing"
        if kind != "file":
            return "payload_missing" if kind == "directory" else "payload_not_regular_file"
        try:
            byte_length, digest = _hash_regular_file(target)
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
    *,
    backup_id: str,
    release: dict[str, Any],
    config_revisions: tuple[dict[str, Any], ...],
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
        backup_id=backup_id,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_generation=generation,
        dataset_revision=revision,
        files=ordered,
        manifest_digest="",
        release=release,
        config_revisions=config_revisions,
        activation_binding=ACTIVATION_ABSENT,
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
    defect = _payload_defect_reason(source_root, manifest)
    if defect is not None:
        raise BackupVerificationError("Backup directory failed shared payload verification.")


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


def _is_direct_v1_backup(root: Path) -> bool:
    """Return True when payload files sit at the backup root without a pointer."""
    if (root / CURRENT_FILENAME).exists():
        return False
    return (root / MANIFEST_FILENAME).exists() or (root / DATABASE_BASENAME).exists()


def _prepare_backup_root(destination_root: Path, source_root: Path) -> Path:
    """Create or reuse a private backup root that is separate from the source."""
    root = _absolute_root(destination_root)
    _reject_overlapping_roots(root, source_root)
    try:
        _mkdir_checked(root)
    except OSError as exc:
        raise RepositoryPathError("Backup destination root could not be prepared.") from exc
    _clear_stale_staging(root)
    if _is_direct_v1_backup(root):
        raise RepositoryBackupError(
            "Existing direct v1 backup is preserved; choose a new destination.",
        )
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
        for staged in backup_root.glob(f"{_STAGING_PREFIX}*"):
            if staged.is_dir() and not staged.is_symlink():
                shutil.rmtree(staged)
            else:
                staged.unlink(missing_ok=True)
    except OSError as exc:
        raise BackupTransferError("Stale backup staging files could not be removed.") from exc


def _copy_regular_file(source: Path, staged: Path) -> tuple[int, str]:
    """Stream one regular file into a private staged path and digest it."""
    digest = hashlib.sha256()
    byte_length = 0
    try:
        source_fd = _open_regular_readonly(source)
        try:
            descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                while True:
                    chunk = os.read(source_fd, _CHUNK_SIZE)
                    if not chunk:
                        break
                    byte_length += len(chunk)
                    digest.update(chunk)
                    _write_all(descriptor, chunk)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(source_fd)
    except (OSError, BackupTransferError) as exc:
        staged.unlink(missing_ok=True)
        if isinstance(exc, BackupTransferError):
            raise
        raise BackupTransferError("Backup payload could not be copied.") from exc
    return byte_length, digest.hexdigest()


def _hash_regular_file(path: Path) -> tuple[int, str]:
    """Return the size and SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    byte_length = 0
    try:
        descriptor = _open_regular_readonly(path)
        try:
            while True:
                chunk = os.read(descriptor, _CHUNK_SIZE)
                if not chunk:
                    break
                byte_length += len(chunk)
                digest.update(chunk)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BackupTransferError("Backup payload could not be hashed.") from exc
    return byte_length, digest.hexdigest()


def _open_regular_readonly(path: Path) -> int:
    """Open one regular file without following a final symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise BackupTransferError("Backup payload must be a regular file.")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _write_private_file(path: Path, data: bytes) -> None:
    """Create one private regular file with the given bytes."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, data)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    """Write every byte, treating a zero-length write as a transfer failure."""
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise BackupTransferError("Backup payload write made no progress.")
        remaining = remaining[written:]


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


def _optional_release(raw: Any) -> dict[str, Any] | None:
    """Validate optional snapshot/program release evidence."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != _RELEASE_KEYS:
        raise BackupIncompleteError("Backup manifest records invalid release evidence.")
    version = _manifest_text(raw, "finjuice_version")
    application_id = _manifest_int(raw, "application_id")
    schema_version = _manifest_int(raw, "schema_version")
    return {
        "application_id": application_id,
        "finjuice_version": version,
        "schema_version": schema_version,
    }


def _optional_config_revisions(raw: Any) -> tuple[dict[str, Any], ...] | None:
    """Validate optional snapshot config-revision references."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise BackupIncompleteError("Backup manifest config revisions must be a list.")
    revisions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != _CONFIG_REVISION_KEYS:
            raise BackupIncompleteError("Backup manifest records an invalid config revision.")
        try:
            revision_id = validate_entity_id(_manifest_text(item, "revision_id"))
        except ValueError as exc:
            raise BackupIncompleteError(
                "Backup manifest records an invalid config revision.",
            ) from exc
        artifact_id = _manifest_text(item, "source_artifact_id")
        if _DIGEST_RE.fullmatch(artifact_id) is None:
            raise BackupIncompleteError("Backup manifest records an invalid config artifact.")
        revisions.append(
            {
                "config_kind": _manifest_text(item, "config_kind"),
                "revision_id": revision_id,
                "source_artifact_id": artifact_id,
            }
        )
    return tuple(revisions)


def _optional_activation(raw: Any) -> str | None:
    """Validate optional activation-binding status."""
    if raw is None:
        return None
    if raw != ACTIVATION_ABSENT:
        raise BackupIncompleteError("Backup manifest records an unsupported activation binding.")
    return ACTIVATION_ABSENT


def _manifest_from_payload(payload: dict[str, Any]) -> BackupManifest:
    """Build a manifest from validated payload fields."""
    unknown = set(payload) - _MANIFEST_KEYS
    if unknown:
        raise BackupIncompleteError("Backup completion manifest contains unsupported fields.")
    manifest = BackupManifest(
        schema_version=_manifest_int(payload, "schema_version"),
        kind=_manifest_text(payload, "kind"),
        backup_id=_manifest_text(payload, "backup_id"),
        created_at=_manifest_text(payload, "created_at"),
        source_generation=_manifest_generation(payload),
        dataset_revision=_manifest_int(payload, "dataset_revision"),
        files=_manifest_files(payload.get("files")),
        manifest_digest=_manifest_digest_text(payload),
        release=_optional_release(payload.get("release")),
        config_revisions=_optional_config_revisions(payload.get("config_revisions")),
        activation_binding=_optional_activation(payload.get("activation_binding")),
    )
    if manifest.schema_version != BACKUP_SCHEMA_VERSION or manifest.kind != BACKUP_KIND:
        raise BackupIncompleteError("Backup was written by an unsupported backup format.")
    return manifest


def _manifest_files(raw: Any) -> tuple[BackupFileEntry, ...]:
    """Validate the recorded payload list of one manifest."""
    if not isinstance(raw, list) or not raw:
        raise BackupIncompleteError("Backup manifest must list at least one payload file.")
    entries = tuple(_manifest_file_entry(item) for item in raw)
    paths = [entry.path for entry in entries]
    if len(paths) != len(set(paths)):
        raise BackupIncompleteError("Backup manifest records duplicate payload paths.")
    if sum(1 for entry in entries if entry.role == _DATABASE_ROLE) != 1:
        raise BackupIncompleteError("Backup manifest must record exactly one database snapshot.")
    return entries


def _manifest_file_entry(raw: Any) -> BackupFileEntry:
    """Validate one recorded payload file entry."""
    if not isinstance(raw, dict):
        raise BackupIncompleteError("Backup manifest file entries must be JSON objects.")
    if set(raw) - _FILE_ENTRY_KEYS:
        raise BackupIncompleteError("Backup manifest file entries contain unsupported fields.")
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
    "CURRENT_FILENAME",
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
    "resolve_backup_payload_root",
    "resolve_generation_database",
    "restore_backup",
]
