"""Small atomic-file primitives shared by legacy storage writers."""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OwnedTempMetadata:
    """Timestamps and mode applied to owned staging before publish."""

    atime_ns: int
    mtime_ns: int
    mode: int


def replace_with_owned_temp(
    target: Path,
    content: bytes,
    *,
    metadata: OwnedTempMetadata | None = None,
) -> None:
    """Replace ``target`` from a unique, exclusively created sibling file."""
    temp_path = _owned_temp_path(target)
    _commit_owned_temp(target, temp_path, _create_owned_temp(temp_path), content, metadata)


def _commit_owned_temp(
    target: Path,
    temp_path: Path,
    descriptor: int,
    content: bytes,
    metadata: OwnedTempMetadata | None,
) -> None:
    opened_identity: tuple[int, int] | None = None
    try:
        opened_identity = _require_private_regular(descriptor)
        _write_all(descriptor, content)
        _apply_staging_attrs(target, temp_path, descriptor, opened_identity, metadata)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temp_path, target)
    except BaseException:
        _cleanup_owned_temp(descriptor, temp_path, opened_identity)
        raise


def _cleanup_owned_temp(descriptor: int, temp_path: Path, identity: tuple[int, int] | None) -> None:
    if descriptor >= 0:
        os.close(descriptor)
    _unlink_if_identity_matches(temp_path, identity)


def _owned_temp_path(target: Path) -> Path:
    return target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"


def _create_owned_temp(temp_path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(temp_path, flags, 0o600)
    except OSError as exc:
        raise OSError("Atomic staging file could not be created safely.") from exc


def _require_private_regular(descriptor: int) -> tuple[int, int]:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        raise OSError("Atomic staging entry is not a private regular file.")
    return (opened.st_dev, opened.st_ino)


def _apply_staging_attrs(
    target: Path,
    temp_path: Path,
    descriptor: int,
    identity: tuple[int, int],
    metadata: OwnedTempMetadata | None,
) -> None:
    if metadata is None:
        _preserve_regular_file_mode(target, descriptor)
        return
    _apply_owned_mode(descriptor, temp_path, identity, metadata.mode)
    _apply_owned_times(descriptor, temp_path, identity, metadata)


def _apply_owned_mode(
    descriptor: int, temp_path: Path, identity: tuple[int, int], mode: int
) -> None:
    mode = stat.S_IMODE(mode)
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, mode)
        return
    _assert_same_identity(temp_path, identity)
    _chmod_without_follow(temp_path, mode)
    _assert_same_identity(temp_path, identity)


def _apply_owned_times(
    descriptor: int,
    temp_path: Path,
    identity: tuple[int, int],
    metadata: OwnedTempMetadata,
) -> None:
    times = (metadata.atime_ns, metadata.mtime_ns)
    if _utime_descriptor(descriptor, times):
        return
    _assert_same_identity(temp_path, identity)
    _utime_without_follow(temp_path, times)
    _assert_same_identity(temp_path, identity)


def _utime_descriptor(descriptor: int, times: tuple[int, int]) -> bool:
    try:
        os.utime(descriptor, ns=times)
    except (OSError, NotImplementedError, TypeError, OverflowError, AttributeError):
        return False
    return True


def _utime_without_follow(path: Path, times: tuple[int, int]) -> None:
    try:
        os.utime(path, ns=times, follow_symlinks=False)
    except (NotImplementedError, TypeError, ValueError):
        os.utime(path, ns=times)


def _chmod_without_follow(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode, follow_symlinks=False)
    except (NotImplementedError, TypeError, ValueError):
        os.chmod(path, mode)


def _assert_same_identity(path: Path, identity: tuple[int, int]) -> None:
    try:
        current = path.lstat()
    except OSError as exc:
        raise OSError("Owned staging entry is no longer the created file.") from exc
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != identity:
        raise OSError("Owned staging entry is no longer the created file.")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Atomic staging write made no progress.")
        remaining = remaining[written:]


def _preserve_regular_file_mode(target: Path, descriptor: int) -> None:
    """Retain an existing regular target's permission bits across replacement."""
    try:
        current = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(current.st_mode) and hasattr(os, "fchmod"):
        os.fchmod(descriptor, stat.S_IMODE(current.st_mode))


def _unlink_if_identity_matches(path: Path, identity: tuple[int, int] | None) -> None:
    """Remove only the staging entry created by this call."""
    if identity is None:
        return
    try:
        current = path.lstat()
    except FileNotFoundError:
        return
    if (current.st_dev, current.st_ino) != identity:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
