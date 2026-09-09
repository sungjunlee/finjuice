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


@contextmanager
def inspection_snapshot(database: Path) -> Iterator[Path]:
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

    with tempfile.TemporaryDirectory(prefix="finjuice-sqlite-inspect-") as temp_dir:
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
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(opened.st_mode):
            raise RepositorySnapshotError("Database inputs must be regular files.")
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
    try:
        before = source.lstat()
    except OSError as exc:
        raise RepositorySnapshotError("Inspection snapshot could not be created.") from exc
    if not stat.S_ISREG(before.st_mode):
        raise RepositorySnapshotError("Database inputs must be regular files.")
    read_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        read_flags |= os.O_NOFOLLOW
    write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        source_fd = os.open(source, read_flags)
    except OSError as exc:
        raise RepositorySnapshotError("Inspection snapshot could not be created.") from exc
    try:
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise RepositorySnapshotError("Database inputs must be regular files.")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise RepositorySnapshotError("Database input changed while it was opened.")
        try:
            destination_fd = os.open(destination, write_flags, 0o600)
        except OSError as exc:
            raise RepositorySnapshotError("Inspection snapshot could not be created.") from exc
        try:
            while True:
                chunk = os.read(source_fd, _CHUNK_SIZE)
                if not chunk:
                    break
                _write_all(destination_fd, chunk)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    except OSError as exc:
        raise RepositorySnapshotError("Inspection snapshot copy failed.") from exc
    finally:
        os.close(source_fd)


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise RepositorySnapshotError("Inspection snapshot write made no progress.")
        remaining = remaining[written:]


def _assert_no_symlink_ancestors(path: Path) -> None:
    """Reject a database path reached through any symlink component."""
    for component in (*path.parents[::-1], path):
        try:
            entry = component.lstat()
        except OSError as exc:
            raise RepositorySnapshotError("Database input is missing or unsafe.") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise RepositorySnapshotError("Database input path must not traverse symlinks.")
        if component != path and not stat.S_ISDIR(entry.st_mode):
            raise RepositorySnapshotError("Database input ancestor must be a directory.")
