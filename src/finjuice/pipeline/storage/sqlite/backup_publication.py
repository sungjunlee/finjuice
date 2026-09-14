"""Durable, no-replace publication for SQLite backup attempts.

This module does not own the backup manifest schema.  It creates private
attempt directories, makes a completed attempt durable, and advances the small
selection pointer after the attempt is published.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.storage.sqlite.errors import (
    BackupTransferError,
    ObjectStoreError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.objects import (
    _assert_no_symlink_ancestors,
    _assert_real_directory_chain,
    _is_link_or_reparse_point,
    _mkdir_checked,
)

ATTEMPTS_DIRNAME: Final = "attempts"
CURRENT_POINTER_FILENAME: Final = "backup-current.json"
MANIFEST_FILENAME: Final = "backup-manifest.json"
POINTER_SCHEMA_VERSION: Final = 1
_ATTEMPT_ID_RE: Final = re.compile(r"^[0-9a-f]{32}$")
_STAGING_PREFIX: Final = ".finjuice-backup-"
_STAGING_SUFFIX: Final = ".tmp"
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class AttemptWorkspace:
    """Private staging paths owned by one backup attempt."""

    container_root: Path
    attempts_root: Path
    staging_root: Path
    attempt_id: str
    _staging_identity: tuple[int, int] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


def prepare_container(destination_root: Path, source_root: Path) -> Path:
    """Prepare a private backup container without touching an existing payload."""
    container = _absolute_path(destination_root)
    source = _absolute_path(source_root)
    _require_real_directory(source, "Backup source root must be a real directory.")
    _reject_overlapping_roots(container, source)
    _reject_direct_legacy_layout(container)
    try:
        _mkdir_checked(container)
        _fsync_parent_chain(container.parent)
    except RepositoryPathError:
        raise
    except ObjectStoreError as exc:
        raise BackupTransferError("Backup container could not be prepared durably.") from exc
    except OSError as exc:
        raise RepositoryPathError("Backup container could not be prepared.") from exc
    _validate_container_namespace(container)
    return container


def begin_attempt(container_root: Path) -> AttemptWorkspace:
    """Create a unique private staging directory below a backup container."""
    container = _absolute_path(container_root)
    try:
        _mkdir_checked(container)
        _fsync_parent_chain(container.parent)
    except RepositoryPathError:
        raise
    except ObjectStoreError as exc:
        raise BackupTransferError("Backup container could not be prepared durably.") from exc
    except OSError as exc:
        raise RepositoryPathError("Backup container could not be prepared.") from exc
    _reject_direct_legacy_layout(container)
    _validate_container_namespace(container)

    attempts = container / ATTEMPTS_DIRNAME
    try:
        _mkdir_checked(attempts, boundary=container)
        _fsync_parent_chain(attempts.parent)
    except RepositoryPathError:
        raise
    except ObjectStoreError as exc:
        raise BackupTransferError(
            "Backup attempts directory could not be prepared durably."
        ) from exc
    except OSError as exc:
        raise RepositoryPathError("Backup attempts directory could not be prepared.") from exc
    _validate_attempts_namespace(attempts)

    attempt_id = uuid.uuid4().hex
    staging = attempts / f"{_STAGING_PREFIX}{attempt_id}{_STAGING_SUFFIX}"
    try:
        staging.mkdir(mode=0o700)
        _require_real_directory(staging, "Backup staging must be a directory.")
        _fsync_directory(attempts)
        identity = _entry_identity(staging)
    except FileExistsError as exc:
        raise BackupTransferError("Backup attempt staging path already exists.") from exc
    except RepositoryPathError:
        raise
    except OSError as exc:
        raise BackupTransferError("Backup attempt staging could not be created.") from exc
    return AttemptWorkspace(container, attempts, staging, attempt_id, identity)


def publish_attempt(workspace: AttemptWorkspace) -> Path:
    """Durably publish one completed staging directory with no replacement."""
    _validate_workspace(workspace, require_staging=True)
    _ensure_staging_identity(workspace)
    try:
        fsync_attempt_tree(workspace.staging_root)
        published = workspace.attempts_root / workspace.attempt_id
        rename_exclusive(workspace.staging_root, published)
        _fsync_parent_chain(workspace.attempts_root)
    except BackupTransferError:
        raise
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup attempt could not be published durably.") from exc
    return published


def discard_attempt(workspace: AttemptWorkspace) -> None:
    """Remove only the still-owned staging directory for an attempt."""
    _validate_workspace_container(workspace)
    staging = workspace.staging_root
    try:
        entry = staging.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BackupTransferError("Backup attempt staging could not be inspected.") from exc
    if workspace._staging_identity is None:
        raise BackupTransferError("Backup attempt staging ownership is unavailable.")
    if _entry_identity_from_stat(entry) != workspace._staging_identity:
        raise BackupTransferError("Backup attempt staging ownership changed.")
    if _is_link_or_reparse_point(entry) or not stat.S_ISDIR(entry.st_mode):
        raise BackupTransferError("Backup attempt staging is not a real directory.")
    try:
        _remove_owned_tree(staging, workspace._staging_identity)
        _fsync_parent_chain(workspace.attempts_root)
    except BackupTransferError:
        raise
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup attempt staging could not be discarded.") from exc


def publish_current_pointer(
    container_root: Path,
    attempt_root: Path,
    manifest_path: Path,
    manifest_digest: str,
) -> None:
    """Atomically select a previously published attempt.

    The attempt and its manifest are never replaced by this operation.  A
    failure after replacement leaves the new attempt retained for inspection;
    the caller must not report a completed backup unless this function returns.
    """
    container = _absolute_path(container_root)
    _reject_direct_legacy_layout(container)
    _validate_container_namespace(container)
    attempts = container / ATTEMPTS_DIRNAME
    _require_real_directory(attempts, "Backup attempts directory must be real.")

    attempt = _absolute_path(attempt_root)
    expected_attempt = attempts / attempt.name
    if attempt != expected_attempt or _ATTEMPT_ID_RE.fullmatch(attempt.name) is None:
        raise BackupTransferError("Backup pointer attempt path is unsafe.")
    _assert_real_directory_chain(container, attempt)
    _require_real_directory(attempt, "Published backup attempt must be a directory.")

    manifest = _absolute_path(manifest_path)
    expected_manifest = attempt / MANIFEST_FILENAME
    if manifest != expected_manifest:
        raise BackupTransferError("Backup pointer manifest path is unsafe.")
    _assert_real_directory_chain(container, manifest.parent)
    if _DIGEST_RE.fullmatch(manifest_digest) is None:
        raise BackupTransferError("Backup pointer manifest digest is invalid.")
    try:
        from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
        from finjuice.pipeline.storage.sqlite.backup_verify import verify_manifest_bytes

        parsed_manifest = verify_manifest_bytes(read_regular_bytes(manifest))
    except Exception as exc:
        raise BackupTransferError("Backup pointer manifest is not a strict v1 manifest.") from exc
    if parsed_manifest.manifest_digest != manifest_digest:
        raise BackupTransferError("Backup pointer manifest digest does not match its self-digest.")

    relative_manifest = f"{ATTEMPTS_DIRNAME}/{attempt.name}/{MANIFEST_FILENAME}"
    payload = {
        "attempt_id": attempt.name,
        "manifest_digest": manifest_digest,
        "manifest_path": relative_manifest,
        "pointer_schema_version": POINTER_SCHEMA_VERSION,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    target = container / CURRENT_POINTER_FILENAME
    _write_pointer_atomic(target, data, container)


def fsync_attempt_tree(root: Path) -> None:
    """Fsync every regular file and directory in an attempt, leaves first."""
    attempt = _absolute_path(root)
    try:
        _assert_no_symlink_ancestors(attempt)
        _require_real_directory(attempt, "Backup attempt must be a real directory.")
        _fsync_tree_directory(attempt)
    except BackupTransferError:
        raise
    except (OSError, RepositoryPathError) as exc:
        raise BackupTransferError("Backup attempt could not be made durable.") from exc


def _fsync_tree_directory(directory: Path) -> None:
    try:
        with os.scandir(directory) as entries:
            children = list(entries)
    except OSError as exc:
        raise BackupTransferError("Backup attempt could not be inventoried safely.") from exc

    for entry in children:
        child = Path(entry.path)
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise BackupTransferError("Backup attempt entry could not be inspected.") from exc
        if _is_link_or_reparse_point(info):
            raise BackupTransferError("Backup attempt contains a symlink or reparse point.")
        if stat.S_ISDIR(info.st_mode):
            _fsync_tree_directory(child)
        elif stat.S_ISREG(info.st_mode):
            _fsync_file(child, info)
        else:
            raise BackupTransferError("Backup attempt contains a special file.")
    _fsync_directory(directory)


def _fsync_file(path: Path, expected: os.stat_result | None = None) -> None:
    try:
        before = path.lstat()
        if _is_link_or_reparse_point(before) or not stat.S_ISREG(before.st_mode):
            raise BackupTransferError("Backup attempt file is not a regular file.")
        if expected is not None and _entry_identity_from_stat(before) != _entry_identity_from_stat(
            expected
        ):
            raise BackupTransferError("Backup attempt file changed while being published.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if _entry_identity_from_stat(opened) != _entry_identity_from_stat(before):
                raise BackupTransferError("Backup attempt file changed while being published.")
            os.fsync(fd)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if _entry_identity_from_stat(after) != _entry_identity_from_stat(before):
            raise BackupTransferError("Backup attempt file changed while being published.")
    except BackupTransferError:
        raise
    except OSError as exc:
        raise BackupTransferError("Backup attempt file could not be made durable.") from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISDIR(opened.st_mode):
                raise BackupTransferError("Backup publication path is not a directory.")
            os.fsync(fd)
        finally:
            os.close(fd)
    except BackupTransferError:
        raise
    except OSError as exc:
        raise BackupTransferError(
            "Backup publication directory could not be made durable."
        ) from exc


def _fsync_parent_chain(parent: Path) -> None:
    current = parent
    while True:
        _fsync_directory(current)
        if current.parent == current:
            return
        current = current.parent


def _write_pointer_atomic(target: Path, data: bytes, container: Path) -> None:
    temp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    identity: tuple[int, int] | None = None
    replaced = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temp, flags, 0o600)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise BackupTransferError("Pointer staging is not a private regular file.")
        identity = _entry_identity_from_stat(opened)
        _write_all(descriptor, data)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temp, target)
        replaced = True
        _fsync_directory(container)
    except BackupTransferError:
        raise
    except OSError as exc:
        raise BackupTransferError("Backup current pointer could not be published durably.") from exc
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if not replaced:
            _unlink_if_identity_matches(temp, identity)


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except OSError as exc:
            raise BackupTransferError("Backup pointer write failed.") from exc
        if written <= 0 or written > len(remaining):
            raise BackupTransferError("Backup pointer write made no progress.")
        remaining = remaining[written:]


def _validate_workspace(workspace: AttemptWorkspace, *, require_staging: bool) -> None:
    _validate_workspace_container(workspace)
    if _ATTEMPT_ID_RE.fullmatch(workspace.attempt_id) is None:
        raise BackupTransferError("Backup attempt ID is not a lowercase hexadecimal value.")
    expected_staging = workspace.attempts_root / (
        f"{_STAGING_PREFIX}{workspace.attempt_id}{_STAGING_SUFFIX}"
    )
    if workspace.staging_root != expected_staging:
        raise BackupTransferError("Backup attempt staging path is unsafe.")
    if require_staging:
        _assert_real_directory_chain(workspace.container_root, workspace.staging_root)
        _require_real_directory(workspace.staging_root, "Backup staging must be a directory.")


def _validate_workspace_container(workspace: AttemptWorkspace) -> None:
    container = _absolute_path(workspace.container_root)
    attempts = _absolute_path(workspace.attempts_root)
    if container != workspace.container_root or attempts != workspace.attempts_root:
        raise BackupTransferError("Backup workspace paths must be absolute and canonical.")
    if attempts != container / ATTEMPTS_DIRNAME:
        raise BackupTransferError("Backup workspace attempts path is unsafe.")
    _assert_no_symlink_ancestors(container)
    _require_real_directory(container, "Backup container must be a directory.")
    _validate_container_namespace(container)
    _assert_real_directory_chain(container, attempts)
    _require_real_directory(attempts, "Backup attempts directory must be a directory.")
    _validate_attempts_namespace(attempts)


def _validate_container_namespace(container: Path) -> None:
    _require_real_directory(container, "Backup container must be a real directory.")
    try:
        with os.scandir(container) as entries:
            items = list(entries)
    except OSError as exc:
        raise RepositoryPathError("Backup container could not be inspected safely.") from exc
    for entry in items:
        info = _entry_stat(entry)
        if entry.name == MANIFEST_FILENAME:
            if _is_link_or_reparse_point(info):
                raise RepositoryPathError("Backup container must not contain symlinks.")
            _raise_legacy_layout()
        if entry.name not in {ATTEMPTS_DIRNAME, CURRENT_POINTER_FILENAME}:
            raise RepositoryPathError("Backup container contains an unsupported top-level entry.")
        if _is_link_or_reparse_point(info):
            raise RepositoryPathError("Backup container must not contain symlinks.")
        if entry.name == ATTEMPTS_DIRNAME and not stat.S_ISDIR(info.st_mode):
            raise RepositoryPathError("Backup attempts entry must be a directory.")
        if entry.name == CURRENT_POINTER_FILENAME and not stat.S_ISREG(info.st_mode):
            raise RepositoryPathError("Backup current pointer must be a regular file.")


def _validate_attempts_namespace(attempts: Path) -> None:
    try:
        with os.scandir(attempts) as entries:
            items = list(entries)
    except OSError as exc:
        raise RepositoryPathError("Backup attempts directory could not be inspected.") from exc
    for entry in items:
        info = _entry_stat(entry)
        if _is_link_or_reparse_point(info) or not stat.S_ISDIR(info.st_mode):
            raise RepositoryPathError("Backup attempts must contain real directories only.")
        if _ATTEMPT_ID_RE.fullmatch(entry.name) is None and not (
            entry.name.startswith(_STAGING_PREFIX)
            and entry.name.endswith(_STAGING_SUFFIX)
            and _ATTEMPT_ID_RE.fullmatch(entry.name[len(_STAGING_PREFIX) : -len(_STAGING_SUFFIX)])
        ):
            raise RepositoryPathError("Backup attempts contains an unsupported entry.")


def _reject_direct_legacy_layout(container: Path) -> None:
    try:
        info = (container / MANIFEST_FILENAME).lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RepositoryPathError("Backup container could not be inspected safely.") from exc
    if _is_link_or_reparse_point(info):
        raise RepositoryPathError("Backup container must not contain symlinks.")
    _raise_legacy_layout()


def _raise_legacy_layout() -> None:
    error = RepositoryPathError("legacy_layout_requires_rebackup")
    setattr(error, "reason", "legacy_layout_requires_rebackup")
    raise error


def _require_real_directory(path: Path, message: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RepositoryPathError(message) from exc
    if _is_link_or_reparse_point(info) or not stat.S_ISDIR(info.st_mode):
        raise RepositoryPathError(message)


def _entry_stat(entry: os.DirEntry[str]) -> os.stat_result:
    try:
        return entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise RepositoryPathError("Backup path entry could not be inspected safely.") from exc


def _entry_identity(path: Path) -> tuple[int, int]:
    return _entry_identity_from_stat(path.lstat())


def _entry_identity_from_stat(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _ensure_staging_identity(workspace: AttemptWorkspace) -> None:
    if workspace._staging_identity is None:
        return
    try:
        current = _entry_identity(workspace.staging_root)
    except OSError as exc:
        raise BackupTransferError("Backup staging ownership could not be checked.") from exc
    if current != workspace._staging_identity:
        raise BackupTransferError("Backup staging ownership changed.")


def _remove_owned_tree(root: Path, expected_identity: tuple[int, int]) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        parent_fd = os.open(root.parent, flags)
        try:
            initial = _stat_at(parent_fd, root.name)
            if _entry_identity_from_stat(initial) != expected_identity:
                raise BackupTransferError("Backup staging ownership changed.")
            _remove_entry_fd(parent_fd, root.name, initial)
        finally:
            os.close(parent_fd)
    except OSError as exc:
        raise BackupTransferError("Backup staging could not be removed safely.") from exc


def _remove_directory_fd(directory_fd: int) -> None:
    with os.scandir(directory_fd) as entries:
        children = list(entries)
    for entry in children:
        _remove_entry_fd(directory_fd, entry.name, entry.stat(follow_symlinks=False))


def _remove_entry_fd(parent_fd: int, name: str, initial: os.stat_result) -> None:
    is_directory = stat.S_ISDIR(initial.st_mode)
    if _is_link_or_reparse_point(initial) or not (is_directory or stat.S_ISREG(initial.st_mode)):
        raise BackupTransferError("Backup staging contains an unsafe entry.")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if is_directory:
        flags |= os.O_DIRECTORY
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        if _entry_identity_from_stat(os.fstat(descriptor)) != _entry_identity_from_stat(initial):
            raise BackupTransferError("Backup staging entry changed during cleanup.")
        if is_directory:
            _remove_directory_fd(descriptor)
    finally:
        os.close(descriptor)
    if _entry_identity_from_stat(_stat_at(parent_fd, name)) != _entry_identity_from_stat(initial):
        raise BackupTransferError("Backup staging entry changed during cleanup.")
    if is_directory:
        os.rmdir(name, dir_fd=parent_fd)
    else:
        os.unlink(name, dir_fd=parent_fd)


def _stat_at(directory_fd: int, name: str) -> os.stat_result:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise BackupTransferError("Backup staging entry could not be inspected.") from exc
    if _is_link_or_reparse_point(info):
        raise BackupTransferError("Backup staging contains a symlink or reparse point.")
    return info


def _unlink_if_identity_matches(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None:
        return
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if _entry_identity_from_stat(current) != identity:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _absolute_path(path: Path) -> Path:
    result = path.expanduser().absolute()
    _assert_no_symlink_ancestors(result, allow_missing=True)
    normalized = result.resolve(strict=False)
    _assert_no_symlink_ancestors(normalized, allow_missing=True)
    return normalized


def _reject_overlapping_roots(root: Path, source: Path) -> None:
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise RepositoryPathError("Backup container and source roots must be separate.")


__all__ = [
    "ATTEMPTS_DIRNAME",
    "AttemptWorkspace",
    "CURRENT_POINTER_FILENAME",
    "MANIFEST_FILENAME",
    "POINTER_SCHEMA_VERSION",
    "begin_attempt",
    "discard_attempt",
    "fsync_attempt_tree",
    "prepare_container",
    "publish_attempt",
    "publish_current_pointer",
]
