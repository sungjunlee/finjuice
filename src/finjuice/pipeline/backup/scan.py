"""Inventory walking, hashing, secret and SQLite guards."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.paths import classify_mode, lstat_or_raise, require_portable_path
from finjuice.pipeline.backup.types import (
    Inventory,
    InventoryEntry,
    RootScan,
    SourceRoot,
    StatIdentity,
)

_HASH_CHUNK = 1024 * 1024
SECRET_BASENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.staging",
    ".env.test",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".netrc",
    "credentials",
    "credentials.json",
    "credentials.toml",
    "auth.json",
    "auth.toml",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SQLITE_NAMES = {"finjuice.sqlite3", "finjuice.db"}
SQLITE_SUFFIXES = ("-wal", "-shm")


def mode_text(mode: int) -> str:
    """Format a POSIX permission mode."""
    return f"{stat.S_IMODE(mode):04o}"


def _open_nofollow_read(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise BackupError(
            "Could not open a source file without following links.",
            code="VALIDATION_FAILED",
        ) from exc


def _identity_from_stat(st: os.stat_result, entry_type: str) -> StatIdentity:
    return StatIdentity(
        dev=st.st_dev,
        ino=st.st_ino,
        size=st.st_size,
        mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)),
        mode=stat.S_IMODE(st.st_mode),
        entry_type=entry_type,  # type: ignore[arg-type]
    )


def _hash_fd(fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, _HASH_CHUNK)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def fingerprint_file(path: Path) -> tuple[StatIdentity, str]:
    """stat/hash/stat a regular file using O_NOFOLLOW when available."""
    first = lstat_or_raise(path)
    classify_mode(first.st_mode)
    fd = _open_nofollow_read(path)
    try:
        hashed = os.fstat(fd)
        if not stat.S_ISREG(hashed.st_mode):
            raise BackupError("Source entry is not a regular file.", code="VALIDATION_FAILED")
        digest = _hash_fd(fd)
        second = os.fstat(fd)
    finally:
        os.close(fd)
    first_id = _identity_from_stat(first, "file")
    second_id = _identity_from_stat(second, "file")
    if first_id != second_id:
        raise BackupError("Source changed during capture.", code="VALIDATION_FAILED")
    return second_id, digest


def fingerprint_directory(path: Path) -> StatIdentity:
    """lstat a real directory."""
    st = lstat_or_raise(path)
    if classify_mode(st.st_mode) != "directory":
        raise BackupError("Expected a directory root.", code="VALIDATION_FAILED")
    return _identity_from_stat(st, "directory")


def is_secret_name(name: str) -> bool:
    """Return whether a basename is a known secret file."""
    lowered = name.lower()
    if lowered in SECRET_BASENAMES or lowered.startswith(".env."):
        return True
    suffix = Path(name).suffix.lower()
    return suffix in SECRET_SUFFIXES


def is_sqlite_name(name: str) -> bool:
    """Return whether a basename is a finjuice SQLite dataset file."""
    lowered = name.lower()
    if lowered in SQLITE_NAMES:
        return True
    return any(lowered == f"{base}{suffix}" for base in SQLITE_NAMES for suffix in SQLITE_SUFFIXES)


def reject_secret_entry(entry: InventoryEntry) -> None:
    """Fail when a known secret file would be copied in plaintext."""
    name = Path(entry.path).name if entry.path != "." else Path(entry.root).name
    if entry.entry_type == "file" and is_secret_name(name):
        raise BackupError(
            "A known secret file was found; plaintext backup is refused.",
            code="VALIDATION_FAILED",
            suggestion="Use a separately tested encrypted recovery route.",
        )


def reject_sqlite_entry(entry: InventoryEntry) -> None:
    """Fail when a live finjuice SQLite dataset would be copied as files."""
    name = Path(entry.path).name
    if entry.entry_type == "file" and is_sqlite_name(name):
        raise BackupError(
            "Active finjuice SQLite datasets are unsupported until Online Backup.",
            code="VALIDATION_FAILED",
            suggestion="Wait for the SQLite Online Backup implementation.",
        )


def _child_portable(parent: str, name: str) -> str:
    if parent == ".":
        return require_portable_path(name)
    return require_portable_path(f"{parent}/{name}")


def _scan_directory(root_path: Path, root_name: str) -> list[InventoryEntry]:
    entries = [_directory_entry(root_name, ".", fingerprint_directory(root_path))]
    stack = [(root_path, ".")]
    while stack:
        current, rel = stack.pop()
        _scan_directory_children(current, rel, root_name, entries, stack)
    entries.sort(key=lambda item: (item.path, item.entry_type))
    return entries


def _scan_directory_children(
    current: Path,
    rel: str,
    root_name: str,
    entries: list[InventoryEntry],
    stack: list[tuple[Path, str]],
) -> None:
    try:
        children = sorted(os.scandir(current), key=lambda item: item.name)
    except OSError as exc:
        raise BackupError(
            "A source directory could not be read.",
            code="FILE_ACCESS_ERROR",
        ) from exc
    for child in children:
        child_rel = _child_portable(rel, child.name)
        child_path = Path(child.path)
        kind = classify_mode(child.stat(follow_symlinks=False).st_mode)
        if kind == "directory":
            identity = fingerprint_directory(child_path)
            entries.append(_directory_entry(root_name, child_rel, identity))
            stack.append((child_path, child_rel))
            continue
        identity, digest = fingerprint_file(child_path)
        entries.append(_file_entry(root_name, child_rel, identity, digest))


def _directory_entry(root: str, path: str, identity: StatIdentity) -> InventoryEntry:
    return InventoryEntry(
        root=root,
        path=path,
        entry_type="directory",
        size=0,
        mode=mode_text(identity.mode),
        mtime_ns=identity.mtime_ns,
        sha256=None,
        identity=identity,
    )


def _file_entry(root: str, path: str, identity: StatIdentity, digest: str) -> InventoryEntry:
    return InventoryEntry(
        root=root,
        path=path,
        entry_type="file",
        size=identity.size,
        mode=mode_text(identity.mode),
        mtime_ns=identity.mtime_ns,
        sha256=digest,
        identity=identity,
    )


def scan_root(spec: SourceRoot) -> RootScan:
    """Scan one inventoried root, including optional absence."""
    if spec.path is None:
        if spec.presence != "optional":
            raise BackupError("A required external root is missing.", code="FILE_NOT_FOUND")
        return RootScan(spec=spec, state="intentionally_absent", entry_type=None)
    if not os.path.lexists(spec.path):
        if spec.presence == "optional":
            return RootScan(spec=spec, state="intentionally_absent", entry_type=None)
        raise BackupError("A required external root is missing.", code="FILE_NOT_FOUND")
    kind = classify_mode(lstat_or_raise(spec.path).st_mode)
    if kind == "file":
        identity, digest = fingerprint_file(spec.path)
        entry = _file_entry(spec.name, ".", identity, digest)
        return RootScan(spec=spec, state="present", entry_type="file", entries=[entry])
    entries = _scan_directory(spec.path, spec.name)
    return RootScan(spec=spec, state="present", entry_type="directory", entries=entries)


def scan_roots(roots: list[SourceRoot]) -> Inventory:
    """Scan every inventoried root and apply secret/SQLite guards."""
    inventory = Inventory()
    for spec in roots:
        scanned = scan_root(spec)
        inventory.roots.append(scanned)
        for entry in scanned.entries:
            reject_secret_entry(entry)
            reject_sqlite_entry(entry)
            inventory.entries.append(entry)
    return inventory


def fingerprints_equal(left: Inventory, right: Inventory) -> bool:
    """Return whether two inventories have the same paths, types, sizes, and digests."""
    left_map = {(item.root, item.path): item for item in left.entries}
    right_map = {(item.root, item.path): item for item in right.entries}
    if set(left_map) != set(right_map):
        return False
    for key, item in left_map.items():
        other = right_map[key]
        if (item.entry_type, item.size, item.sha256, item.mode, item.mtime_ns) != (
            other.entry_type,
            other.size,
            other.sha256,
            other.mode,
            other.mtime_ns,
        ):
            return False
        if item.identity is not None and other.identity is not None:
            if item.identity != other.identity:
                return False
    return True
