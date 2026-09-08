"""Path safety helpers for backup create/verify/restore."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.types import DATA_ROOT_NAME
from finjuice.pipeline.config import is_inside_program_repo, validate_not_program_repo_path

ROOT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def expand_user_path(path: Path) -> Path:
    """Expand ``~`` without resolving symlinks."""
    return Path(os.path.expanduser(str(path)))


def absolute_unresolved(path: Path) -> Path:
    """Return an absolute path without following symlinks."""
    expanded = expand_user_path(path)
    if expanded.is_absolute():
        return expanded
    return Path(os.getcwd()) / expanded


def _symlink_error() -> BackupError:
    return BackupError(
        "A backup path is a symlink or has a symlink ancestor.",
        code="VALIDATION_FAILED",
        suggestion="Use real directories or files, not symlinks.",
    )


def reject_symlink_chain(path: Path) -> Path:
    """Reject symlink roots or ancestors and return a dot-normalized path."""
    absolute = absolute_unresolved(path)
    _reject_symlinks_in_ancestors(absolute)
    normalized = Path(os.path.abspath(absolute))
    _reject_symlinks_in_ancestors(normalized)
    return normalized


def _reject_symlinks_in_ancestors(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current) and os.path.islink(current):
            raise _symlink_error()
        parent = current.parent
        if parent == current:
            break
        current = parent


def require_outside_program_repo(path: Path, *, context: str) -> Path:
    """Reject program-repo paths after the symlink-chain check."""
    absolute = reject_symlink_chain(path)
    try:
        validate_not_program_repo_path(absolute, context=context)
    except ValueError as exc:
        raise BackupError(
            "Refusing a backup path inside the program repository.",
            code="INVALID_ARGS",
        ) from exc
    if is_inside_program_repo(absolute) or _is_inside_finjuice_checkout(absolute):
        raise BackupError(
            "Refusing a backup path inside the program repository.",
            code="INVALID_ARGS",
        )
    return absolute


def _is_inside_finjuice_checkout(path: Path) -> bool:
    """Detect a target finjuice checkout even when running from an installed wheel."""
    for candidate in (path, *path.parents):
        if (
            (candidate / ".git").exists()
            and (candidate / "pyproject.toml").is_file()
            and (candidate / "src" / "finjuice").is_dir()
        ):
            return True
    return False


def paths_overlap(left: Path, right: Path) -> bool:
    """Detect lexical containment and existing filesystem aliases."""
    return (
        left == right
        or left in right.parents
        or right in left.parents
        or _physical_ancestor(left, right)
        or _physical_ancestor(right, left)
    )


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BackupError("A backup path could not be read.", code="FILE_ACCESS_ERROR") from exc
    if stat.S_ISLNK(info.st_mode):
        raise _symlink_error()
    return info.st_dev, info.st_ino


def _physical_ancestor(parent: Path, child: Path) -> bool:
    identity = _path_identity(parent)
    if identity is None:
        return False
    return any(_path_identity(candidate) == identity for candidate in (child, *child.parents))


def reject_overlap(left: Path, right: Path, *, code: str = "INVALID_ARGS") -> None:
    """Fail when two backup paths overlap."""
    if paths_overlap(left, right):
        raise BackupError("Backup paths overlap.", code=code)


def validate_root_name(name: str) -> str:
    """Return a validated logical root name."""
    if name == DATA_ROOT_NAME:
        raise BackupError(
            "The data root name is reserved for --source.",
            code="INVALID_ARGS",
        )
    if not ROOT_NAME_RE.fullmatch(name):
        raise BackupError("Invalid source-root name.", code="INVALID_ARGS")
    return name


def parse_named_root(raw: str) -> tuple[str, str]:
    """Parse ``NAME=PATH`` into a logical name and path text."""
    if "=" not in raw:
        raise BackupError("source-root must be NAME=PATH.", code="INVALID_ARGS")
    name, _, path_text = raw.partition("=")
    return validate_root_name(name.strip()), path_text


def lstat_or_raise(path: Path) -> os.stat_result:
    """lstat a path, mapping missing files to a safe error."""
    try:
        return os.lstat(path)
    except FileNotFoundError as exc:
        raise BackupError("A required backup path is missing.", code="FILE_NOT_FOUND") from exc
    except OSError as exc:
        raise BackupError("A backup path could not be read.", code="FILE_ACCESS_ERROR") from exc


def classify_mode(mode: int) -> str:
    """Classify an lstat mode as file, directory, or unsupported."""
    if stat.S_ISLNK(mode):
        raise BackupError(
            "Symlinks are not allowed in backup capture.",
            code="VALIDATION_FAILED",
        )
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    raise BackupError(
        "Special files are not allowed in backup capture.",
        code="VALIDATION_FAILED",
    )


def portable_path_errors(path: str) -> str | None:
    """Return a reason code if a portable path is illegal."""
    if path == ".":
        return None
    checks = (
        (not path, "empty"),
        ("\x00" in path, "nul"),
        ("\\" in path, "backslash"),
        (path.startswith("/") or path.startswith("~"), "absolute"),
        (re.match(r"^[A-Za-z]:", path) is not None, "windows_drive"),
        (any(part in {"", ".", ".."} for part in path.split("/")), "dot_segment"),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return None


def require_portable_path(path: str) -> str:
    """Validate a restore-safe relative portable path."""
    reason = portable_path_errors(path)
    if reason is not None:
        raise BackupError("Backup manifest contains an unsafe path.", code="VALIDATION_FAILED")
    return path
