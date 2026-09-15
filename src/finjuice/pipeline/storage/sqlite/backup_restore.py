"""Isolated restore helpers for SQLite generation backups.

Owns destination-root preparation, payload republishing, restored-database
checks, and failed-restore rollback. Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.backup`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Final

from finjuice.pipeline.storage.sqlite.backup_publication import fsync_attempt_tree
from finjuice.pipeline.storage.sqlite.backup_verify import (
    copy_regular_file,
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
    _mkdir_checked,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import _validate_connection

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.backup import BackupManifest, RestoreResult
    from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo

_DATABASE_BASENAME: Final = "finjuice.sqlite3"
_MANIFEST_FILENAME: Final = "backup-manifest.json"
_OBJECT_ROLE: Final = "object"
_STAGING_PREFIX: Final = ".finjuice-backup-"


def _restore_backup_unlocked(backup_root: Path, destination: Path) -> RestoreResult:
    from finjuice.pipeline.storage.sqlite.backup import RestoreResult, _absolute_root

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


def _restore_database(
    source_root: Path,
    manifest: BackupManifest,
    target_paths: GenerationPaths,
    warnings: list[str],
) -> None:
    """Copy the snapshot into the restore root and prove its digest."""
    from finjuice.pipeline.storage.sqlite.backup import _publish_staged_file

    entry = manifest.entry(_DATABASE_BASENAME)
    staged = target_paths.root / f"{_STAGING_PREFIX}restore-{uuid.uuid4().hex}.tmp"
    byte_length, digest = _copy_regular_file(source_root / _DATABASE_BASENAME, staged)
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
    from finjuice.pipeline.storage.sqlite.backup import _connect_readonly

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
    from finjuice.pipeline.storage.sqlite.backup import (
        _record_directory_fsync,
        _write_private_file,
    )

    try:
        raw = read_regular_bytes(source_root / _MANIFEST_FILENAME)
    except OSError as exc:
        raise BackupIncompleteError("Backup completion manifest disappeared.") from exc
    if verify_manifest_bytes(raw) != manifest:
        raise BackupVerificationError("Backup manifest bytes changed during restore.")
    staged = target_root / f"{_STAGING_PREFIX}manifest-{uuid.uuid4().hex}.tmp"
    try:
        _write_private_file(staged, raw)
        os.replace(staged, target_root / _MANIFEST_FILENAME)
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
    from finjuice.pipeline.storage.sqlite.backup import _absolute_root

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


def _copy_regular_file(source: Path, staged: Path) -> tuple[int, str]:
    try:
        return copy_regular_file(source, staged)
    except RepositoryBackupError as exc:
        raise BackupTransferError("Backup payload could not be transferred safely.") from exc
