"""Staging, copy, space preflight, and atomic publish helpers."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from finjuice.pipeline.backup.errors import BackupError, invalid
from finjuice.pipeline.backup.paths import classify_mode, lstat_or_raise
from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.backup.scan import fingerprint_file
from finjuice.pipeline.backup.types import InventoryEntry, SourceRoot

_COPY_CHUNK = 1024 * 1024


def fsync_fd(fd: int) -> None:
    """Flush a file descriptor to durable storage."""
    os.fsync(fd)


def fsync_path(path: Path) -> None:
    """fsync a file path."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fsync_fd(fd)
    finally:
        os.close(fd)


def fsync_directory(path: Path) -> None:
    """fsync a directory when the platform supports it."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        fsync_fd(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
            raise
    finally:
        os.close(fd)


def fsync_tree(root: Path) -> None:
    """Flush every directory entry in a completed tree from leaves to root."""
    directories: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        directories.append(current)
        for name in dirnames + filenames:
            if (current / name).is_symlink():
                raise invalid("Backup staging contains a symlink.")
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)


def mkdir_private(path: Path) -> None:
    """Create a 0700 directory, refusing to reuse an existing path."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise BackupError("Backup staging path already exists.", code="FILE_ACCESS_ERROR") from exc
    os.chmod(path, 0o700)


def preflight_space(parent: Path, needed_bytes: int) -> None:
    """Fail when free space is below the captured byte count plus a margin."""
    try:
        usage = shutil.disk_usage(parent)
    except OSError as exc:
        raise BackupError("Could not inspect free disk space.", code="FILE_ACCESS_ERROR") from exc
    margin = max(1024 * 1024, needed_bytes // 10)
    if usage.free < needed_bytes + margin:
        raise BackupError("Insufficient disk space for backup.", code="FILE_ACCESS_ERROR")


def _raise_io(exc: OSError) -> NoReturn:
    if exc.errno == errno.ENOSPC:
        raise BackupError("Disk is full.", code="FILE_ACCESS_ERROR") from exc
    raise BackupError("Backup I/O failed.", code="FILE_ACCESS_ERROR") from exc


def copy_regular_file(source: Path, destination: Path, mode: int, mtime_ns: int) -> None:
    """Copy one regular file without following symlinks."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        src_fd = os.open(source, flags)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise BackupError("Source changed during capture.", code="VALIDATION_FAILED") from exc
        _raise_io(exc)
    try:
        _write_copy_fd(src_fd, destination, mode, mtime_ns)
    finally:
        os.close(src_fd)


def _write_copy_fd(src_fd: int, destination: Path, mode: int, mtime_ns: int) -> None:
    st = os.fstat(src_fd)
    if not stat.S_ISREG(st.st_mode):
        raise BackupError("Source entry is not a regular file.", code="VALIDATION_FAILED")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        dest_fd = os.open(destination, flags, 0o600)
    except OSError as exc:
        _raise_io(exc)
        return
    try:
        _copy_bytes(src_fd, dest_fd)
        os.fchmod(dest_fd, stat.S_IMODE(mode))
        os.utime(dest_fd, ns=(mtime_ns, mtime_ns))
        fsync_fd(dest_fd)
    except OSError as exc:
        os.close(dest_fd)
        destination.unlink(missing_ok=True)
        _raise_io(exc)
        return
    os.close(dest_fd)


def _copy_bytes(src_fd: int, dest_fd: int) -> None:
    while True:
        chunk = os.read(src_fd, _COPY_CHUNK)
        if not chunk:
            return
        _write_all(dest_fd, chunk)


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "Write made no progress")
        remaining = remaining[written:]


def payload_root_dir(staging: Path, spec: SourceRoot) -> Path:
    """Return the staging payload directory for a logical root."""
    from finjuice.pipeline.backup.types import DATA_ROOT_NAME, PAYLOAD_DIRNAME, ROOTS_DIRNAME

    if spec.name == DATA_ROOT_NAME:
        return staging / PAYLOAD_DIRNAME / DATA_ROOT_NAME
    return staging / PAYLOAD_DIRNAME / ROOTS_DIRNAME / spec.name


def copy_inventory(
    roots: list[SourceRoot],
    entries: list[InventoryEntry],
    staging: Path,
) -> None:
    """Copy scanned entries into staging without modifying source."""
    by_name = {spec.name: spec for spec in roots}
    directory_metadata: list[tuple[Path, int, int]] = []
    for entry in sorted(entries, key=lambda item: (item.root, item.path, item.entry_type)):
        spec = by_name[entry.root]
        if spec.path is None:
            continue
        destination = _copy_entry(spec, entry, staging)
        if entry.entry_type == "directory":
            directory_metadata.append((destination, int(entry.mode, 8), entry.mtime_ns))
    finalize_directory_metadata(directory_metadata)


def _copy_entry(spec: SourceRoot, entry: InventoryEntry, staging: Path) -> Path:
    if spec.path is None:
        raise invalid("Backup source root is missing.")
    source = spec.path if entry.path == "." else spec.path / entry.path
    dest_root = payload_root_dir(staging, spec)
    destination = dest_root if entry.path == "." else dest_root / entry.path
    if entry.entry_type == "directory":
        destination.mkdir(parents=True, exist_ok=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy_regular_file(source, destination, int(entry.mode, 8), entry.mtime_ns)
    copied = fingerprint_file(destination)
    if copied[1] != entry.sha256 or copied[0].size != entry.size:
        raise BackupError("Source changed during capture.", code="VALIDATION_FAILED")
    if copied[0].mtime_ns != entry.mtime_ns or copied[0].mode != int(entry.mode, 8):
        raise BackupError("Backup metadata could not be preserved.", code="VALIDATION_FAILED")
    return destination


def finalize_directory_metadata(directories: list[tuple[Path, int, int]]) -> None:
    """Apply directory mode and mtime after children exist, then make them durable."""
    ordered = sorted(directories, key=lambda item: len(item[0].parts), reverse=True)
    for path, mode, mtime_ns in ordered:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            os.fchmod(fd, stat.S_IMODE(mode))
            os.utime(fd, ns=(mtime_ns, mtime_ns))
            fsync_fd(fd)
            current = os.fstat(fd)
        finally:
            os.close(fd)
        current_mtime = getattr(current, "st_mtime_ns", int(current.st_mtime * 1_000_000_000))
        if stat.S_IMODE(current.st_mode) != stat.S_IMODE(mode) or current_mtime != mtime_ns:
            raise invalid("Backup directory metadata could not be preserved.")


def new_staging_dir(parent: Path) -> Path:
    """Return a unique private staging directory next to the final path."""
    return parent / f".finjuice-backup-staging-{uuid.uuid4().hex}"


def cleanup_tree(path: Path) -> None:
    """Remove a staging tree, ignoring missing paths."""
    shutil.rmtree(path, ignore_errors=True)


def atomic_publish(staging: Path, output: Path, *, replace_empty: bool = False) -> None:
    """Publish a completed staging tree with a directory fsync."""
    fsync_tree(staging)
    try:
        if replace_empty:
            # POSIX rename leaves the existing destination in place on failure,
            # and refuses to replace a non-empty directory.
            os.rename(staging, output)
        else:
            rename_exclusive(staging, output)
    except OSError as exc:
        cleanup_tree(staging)
        if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise BackupError(
                "Output already exists and was not overwritten.",
                code="VALIDATION_FAILED",
            ) from exc
        _raise_io(exc)
    fsync_directory(output.parent)


def write_text_atomic(path: Path, text: str) -> None:
    """Write text, fsync, and refuse to overwrite."""
    data = text.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        _raise_io(exc)
        return
    try:
        _write_all(fd, data)
        fsync_fd(fd)
    except OSError as exc:
        os.close(fd)
        path.unlink(missing_ok=True)
        _raise_io(exc)
        return
    os.close(fd)


def restore_payload_destination(target: Path, root_name: str) -> Path:
    """Return the isolated restore layout path for a logical root."""
    from finjuice.pipeline.backup.types import DATA_ROOT_NAME, ROOTS_DIRNAME

    if root_name == DATA_ROOT_NAME:
        return target / DATA_ROOT_NAME
    return target / ROOTS_DIRNAME / root_name


def copy_payload_entry(backup_root: Path, destination: Path, entry: dict[str, object]) -> None:
    """Copy one verified payload entry into a restore staging tree."""
    from finjuice.pipeline.backup.manifest import payload_relative
    from finjuice.pipeline.backup.paths import reject_symlink_chain

    rel = payload_relative(str(entry["root"]), str(entry["path"]))
    source = backup_root / rel
    reject_symlink_chain(source)
    kind = classify_mode(lstat_or_raise(source).st_mode)
    if kind != entry["type"]:
        raise invalid("Backup payload type does not match the manifest.")
    if entry["type"] == "directory":
        destination.mkdir(parents=True, exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy_regular_file(
        source,
        destination,
        int(str(entry["mode"]), 8),
        int(str(entry["mtime_ns"])),
    )
    _check_restored_digest(destination, entry)


def _check_restored_digest(destination: Path, entry: dict[str, object]) -> None:
    identity, digest = fingerprint_file(destination)
    expected = entry.get("sha256")
    expected_digest = None if expected is None else str(expected).removeprefix("sha256:")
    if expected_digest is None or digest != expected_digest:
        raise invalid("Restored bytes do not match the manifest digest.")
    if identity.size != int(str(entry["size"])):
        raise invalid("Restored bytes do not match the manifest digest.")
    if identity.mode != int(str(entry["mode"]), 8) or identity.mtime_ns != int(
        str(entry["mtime_ns"])
    ):
        raise invalid("Restored file metadata does not match the manifest.")


def run_with_staging(parent: Path, action: Callable[[Path], None], output: Path) -> None:
    """Run ``action`` inside a private staging directory and publish it."""
    staging = new_staging_dir(parent)
    mkdir_private(staging)
    try:
        action(staging)
        atomic_publish(staging, output)
    except BackupError:
        cleanup_tree(staging)
        raise
    except OSError as exc:
        cleanup_tree(staging)
        _raise_io(exc)
    except Exception:
        cleanup_tree(staging)
        raise
