"""Publish directories atomically without replacing an existing path."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from finjuice.pipeline.backup.errors import BackupError


def require_mutation_platform() -> None:
    """Reject runtimes without the supported directory durability primitives."""
    if sys.platform not in {"linux", "darwin"}:
        raise BackupError(
            "Backup create and restore require Linux or macOS.",
            code="INVALID_ARGS",
            suggestion="Use a supported host with directory fsync and atomic rename support.",
        )


def rename_exclusive(source: Path, destination: Path) -> None:
    """Rename a sibling directory with the platform's no-replace primitive.

    Linux uses renameat2(RENAME_NOREPLACE); macOS uses
    renameatx_np(RENAME_EXCL). An unsupported runtime fails closed.
    """
    if source.parent != destination.parent:
        raise OSError(errno.EXDEV, "Publication requires sibling directories")
    _rename_posix(source, destination)


def _rename_posix(source: Path, destination: Path) -> None:
    primitives = {"linux": ("renameat2", 1), "darwin": ("renameatx_np", 4)}
    if sys.platform not in primitives:
        raise OSError(errno.ENOTSUP, "Exclusive directory publication is unsupported")
    name, flags = primitives[sys.platform]
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = getattr(libc, name)
    except AttributeError as exc:
        raise OSError(errno.ENOTSUP, "Exclusive directory publication is unsupported") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        result = rename(
            parent_fd, os.fsencode(source.name), parent_fd, os.fsencode(destination.name), flags
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(parent_fd)
