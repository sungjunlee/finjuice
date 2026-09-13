"""Versioned, immutable migration evidence and privacy-safe results."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup.paths import reject_symlink_chain

PLAN_VERSION = "finjuice.migration.plan.v1"
MIGRATION_VERSION = "finjuice.migration.v1"
ATTEMPT_MIGRATION_VERSION = "finjuice.migration.v2"
MARKER = "FINJUICE_MIGRATION_COMPLETE"
MANIFEST = "migration-manifest.json"


class MigrationError(ValueError):
    """Invalid, changed, incomplete, or non-isolated migration evidence."""


@dataclass(frozen=True)
class MigrationResult:
    """Serializable operation result; detailed evidence stays in private artifacts."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "canonical_digest": digest(payload)}


def load_sealed(path: Path, version: str) -> dict[str, Any]:
    reject_symlink_chain(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError("Migration evidence cannot be read.") from exc
    if not isinstance(payload, dict):
        raise MigrationError("Migration evidence must be an object.")
    checksum = payload.get("canonical_digest")
    unsigned = {key: value for key, value in payload.items() if key != "canonical_digest"}
    if payload.get("schema_version") != version or checksum != digest(unsigned):
        raise MigrationError("Migration evidence version or digest does not match.")
    return payload


def tree_inventory(root: Path) -> list[dict[str, Any]]:
    """Bind every frozen-tree entry, including additions outside its payload."""
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            reject_symlink_chain(path)
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise MigrationError("Frozen source contains an unsupported entry.")
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "directory" if path.is_dir() else "file",
                    "sha256": file_digest(path) if path.is_file() else None,
                    "mode": stat.S_IMODE(info.st_mode),
                    "mtime_ns": info.st_mtime_ns,
                }
            )
    return sorted(result, key=lambda entry: entry["path"])


def load_migration_manifest(path: Path) -> dict[str, Any]:
    """Read either original preservation or required attempt-evidence manifests."""
    try:
        return load_sealed(path, ATTEMPT_MIGRATION_VERSION)
    except MigrationError:
        return load_sealed(path, MIGRATION_VERSION)
