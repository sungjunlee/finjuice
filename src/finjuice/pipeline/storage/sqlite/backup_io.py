"""Descriptor-based regular-file I/O for strict SQLite backup verification."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path

from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError


class BackupPayloadError(BackupVerificationError):
    """A static verification failure with a stable machine-readable reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Backup verification failed: " + reason + ".")


def checked_directories(path: Path) -> tuple[tuple[Path, int, int], ...]:
    """Reject symlink/non-directory ancestors and retain their identity for rechecks."""
    result = []
    for parent in reversed((path.absolute(), *path.absolute().parents)):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise BackupPayloadError("unsafe_path")
        result.append((parent, info.st_dev, info.st_ino))
    return tuple(result)


def _stable(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(
    path: Path, consume: Callable[[bytes], None], *, max_bytes: int | None = None
) -> tuple[int, str]:
    try:
        ancestors = checked_directories(path.parent)
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise BackupPayloadError("unsafe_file")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _stable(initial) != _stable(opened):
                raise BackupPayloadError("payload_changed")
            if max_bytes is not None and opened.st_size > max_bytes:
                raise BackupPayloadError("payload_too_large")
            length, digest = _consume_descriptor(descriptor, consume, max_bytes)
            if _stable(opened) != _stable(os.fstat(descriptor)) or length != opened.st_size:
                raise BackupPayloadError("payload_changed")
            if _stable(path.lstat()) != _stable(opened):
                raise BackupPayloadError("payload_changed")
            if checked_directories(path.parent) != ancestors:
                raise BackupPayloadError("payload_changed")
            return length, digest
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        raise BackupPayloadError("payload_missing") from None
    except OSError:
        raise BackupPayloadError("payload_unreadable") from None


def _consume_descriptor(
    descriptor: int, consume: Callable[[bytes], None], max_bytes: int | None
) -> tuple[int, str]:
    """Stream within the budget, rejecting the overflow byte before consuming it."""
    digest, length = hashlib.sha256(), 0
    while True:
        budget = 1024 * 1024 if max_bytes is None else min(1024 * 1024, max_bytes - length + 1)
        chunk = os.read(descriptor, budget)
        if not chunk:
            break
        if max_bytes is not None and length + len(chunk) > max_bytes:
            raise BackupPayloadError("payload_too_large")
        consume(chunk)
        digest.update(chunk)
        length += len(chunk)
    return length, digest.hexdigest()


def read_regular_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    """Read stable regular-file bytes with an optional limit and no symbolic links."""
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be nonnegative")
    chunks: list[bytes] = []
    _read(path, chunks.append, max_bytes=max_bytes)
    return b"".join(chunks)


def fingerprint_regular_file(path: Path) -> tuple[int, str]:
    """Stream and fingerprint one stable regular file."""
    return _read(path, lambda chunk: None)


def _write_all(descriptor: int, chunk: bytes) -> None:
    pending = memoryview(chunk)
    while pending:
        written = os.write(descriptor, pending)
        if written <= 0:
            raise BackupPayloadError("payload_write_failed")
        pending = pending[written:]


def copy_regular_file(source: Path, staged: Path) -> tuple[int, str]:
    """Exclusively create a private staged file, fully write/fsync, and prove source stability."""
    descriptor = None
    owned = None
    try:
        ancestors = checked_directories(staged.parent)
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        info = os.fstat(descriptor)
        owned = (info.st_dev, info.st_ino)
        result = _read(source, lambda chunk: _write_all(descriptor, chunk))
        os.fsync(descriptor)
        current = staged.lstat()
        if (current.st_dev, current.st_ino) != owned or checked_directories(
            staged.parent
        ) != ancestors:
            raise BackupPayloadError("payload_changed")
        return result
    except Exception:
        if owned is not None:
            try:
                current = staged.lstat()
                if (current.st_dev, current.st_ino) == owned:
                    staged.unlink()
            except OSError:
                pass
        raise BackupPayloadError("payload_copy_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
