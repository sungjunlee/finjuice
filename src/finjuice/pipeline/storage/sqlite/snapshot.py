"""Side-effect-free SQLite inspection snapshots, including committed WAL state."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterator

from finjuice.pipeline.storage.sqlite.errors import RepositorySnapshotError

_CHUNK_SIZE: Final = 1024 * 1024


@dataclass(frozen=True)
class _Fingerprint:
    dev: int
    ino: int
    size: int
    mtime_ns: int
    digest: str


def default_inspection_scratch_root() -> Path:
    """Return the private application-cache root used for inspection copies."""
    configured = os.environ.get("XDG_CACHE_HOME")
    cache_root = Path(configured).expanduser() if configured else Path.home() / ".cache"
    if not cache_root.is_absolute():
        raise RepositorySnapshotError("Inspection cache root must be absolute.")
    return cache_root / "finjuice" / "sqlite-inspection"


@contextmanager
def inspection_snapshot(
    database: Path,
    *,
    scratch_root: Path | None = None,
) -> Iterator[Path]:
    """Copy a stable DB/WAL pair to scratch without opening the original via SQLite."""
    source = database.expanduser().absolute()
    _assert_no_symlink_ancestors(source)
    journal = Path(f"{source}-journal")
    if journal.exists():
        raise RepositorySnapshotError("Database has an active rollback journal.")
    wal = Path(f"{source}-wal")
    source_paths = [source]
    if wal.exists():
        source_paths.append(wal)
    before = {path.name: _fingerprint(path) for path in source_paths}

    requested_scratch = (scratch_root or default_inspection_scratch_root()).expanduser().absolute()
    if requested_scratch == source.parent or requested_scratch.is_relative_to(source.parent):
        raise RepositorySnapshotError("Inspection scratch root must be outside the generation.")
    scratch = _prepare_scratch_root(requested_scratch)
    with tempfile.TemporaryDirectory(
        prefix="finjuice-sqlite-inspect-",
        dir=scratch,
    ) as temp_dir:
        scratch_dir = Path(temp_dir)
        for source_path in source_paths:
            _copy_regular(source_path, scratch_dir / source_path.name)
        copied = {path.name: _fingerprint(scratch_dir / path.name) for path in source_paths}
        copied_content = {
            name: (fingerprint.size, fingerprint.digest) for name, fingerprint in copied.items()
        }
        source_content = {
            name: (fingerprint.size, fingerprint.digest) for name, fingerprint in before.items()
        }
        if copied_content != source_content:
            raise RepositorySnapshotError("Inspection snapshot bytes do not match the source.")
        after_names = [source]
        if wal.exists():
            after_names.append(wal)
        if [path.name for path in after_names] != [path.name for path in source_paths]:
            raise RepositorySnapshotError("Database sidecar set changed during inspection.")
        after = {path.name: _fingerprint(path) for path in after_names}
        if before != after:
            raise RepositorySnapshotError("Database changed during inspection snapshot capture.")
        if journal.exists():
            raise RepositorySnapshotError("Rollback journal appeared during inspection.")
        yield scratch_dir / source.name


def _fingerprint(path: Path) -> _Fingerprint:
    fd, before = _open_regular_read(path)
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        while True:
            chunk = os.read(fd, _CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != opened_identity or opened_identity != after_identity:
        raise RepositorySnapshotError("Database input changed while it was hashed.")
    return _Fingerprint(
        dev=after.st_dev,
        ino=after.st_ino,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        digest=digest.hexdigest(),
    )


def _copy_regular(source: Path, destination: Path) -> None:
    source_fd, _ = _open_regular_read(source)
    try:
        destination_fd = _open_scratch_destination(destination)
        try:
            _copy_bytes(source_fd, destination_fd)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _open_regular_read(path: Path) -> tuple[int, os.stat_result]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RepositorySnapshotError("Database input is missing or unsafe.") from exc
    if not stat.S_ISREG(before.st_mode):
        raise RepositorySnapshotError("Database inputs must be regular files.")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RepositorySnapshotError("Database input is missing or unsafe.") from exc
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode):
        os.close(fd)
        raise RepositorySnapshotError("Database inputs must be regular files.")
    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
        os.close(fd)
        raise RepositorySnapshotError("Database input changed while it was opened.")
    return fd, before


def _open_scratch_destination(destination: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        return os.open(destination, flags, 0o600)
    except OSError as exc:
        raise RepositorySnapshotError("Inspection snapshot could not be created.") from exc


def _copy_bytes(source_fd: int, destination_fd: int) -> None:
    try:
        while True:
            chunk = os.read(source_fd, _CHUNK_SIZE)
            if not chunk:
                return
            _write_all(destination_fd, chunk)
    except OSError as exc:
        raise RepositorySnapshotError("Inspection snapshot copy failed.") from exc


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise RepositorySnapshotError("Inspection snapshot write made no progress.")
        remaining = remaining[written:]


def _prepare_scratch_root(path: Path) -> Path:
    root = path.expanduser().absolute()
    _assert_no_symlink_ancestors(root, allow_missing=True)
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        entry = root.lstat()
    except OSError as exc:
        raise RepositorySnapshotError("Inspection scratch root could not be prepared.") from exc
    _assert_no_symlink_ancestors(root)
    if not stat.S_ISDIR(entry.st_mode) or stat.S_IMODE(entry.st_mode) & 0o077:
        raise RepositorySnapshotError("Inspection scratch root must be a private directory.")
    return root


def _assert_no_symlink_ancestors(path: Path, *, allow_missing: bool = False) -> None:
    """Reject a database path reached through any redirecting path component."""
    for component in (*path.parents[::-1], path):
        try:
            entry = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise RepositorySnapshotError("Database input is missing or unsafe.") from None
        except OSError as exc:
            raise RepositorySnapshotError("Database input is missing or unsafe.") from exc
        file_attributes = getattr(entry, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(entry.st_mode) or file_attributes & reparse_flag:
            raise RepositorySnapshotError(
                "Database input path must not traverse symlinks or reparse points."
            )
        if component != path and not stat.S_ISDIR(entry.st_mode):
            raise RepositorySnapshotError("Database input ancestor must be a directory.")
