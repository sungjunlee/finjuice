"""Graph inventory and manifest-schema helpers for a local recovery graph.

Owns layout constants, file inventory, role maps, and payload schema checks.
Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.recovery_bundle`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.sqlite.backup_io import (
    checked_directories,
    fingerprint_regular_file,
)
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError

_ERROR = "Local recovery graph proof or independently trusted evidence could not be verified."
_MANIFEST = "recovery-graph.json"
_KIND = "finjuice.sqlite.local-recovery-graph"
_ACTIVATION = "activation/active.json"
_LOCK = "release/dependency.lock"
_BINDING = "release/binding.json"
_KEYS = {
    "graph_schema_version",
    "kind",
    "roles",
    "activation",
    "activation_sha256",
    "snapshot_generation",
    "snapshot_schema_version",
    "snapshot_revision",
    "snapshot_backup_id",
    "wheel_basename",
    "files",
    "graph_digest",
}


def _files(root: Path, basename: str) -> list[dict[str, Any]]:
    release = {f"release/{basename}", _LOCK, _BINDING}
    names: list[str] = []
    pending = [root]
    while pending:
        parent = pending.pop()
        checked_directories(parent)
        for path in parent.iterdir():
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                _require(not relative.startswith(("activation/", "release/")))
                if parent == root and relative not in {
                    "activation",
                    "release",
                    "capsule",
                    "snapshot",
                }:
                    raise BackupVerificationError(_ERROR)
                pending.append(path)
            elif stat.S_ISREG(mode):
                if parent == root and relative != _MANIFEST:
                    raise BackupVerificationError(_ERROR)
                names.append(relative)
            else:
                raise BackupVerificationError(_ERROR)
    payload = [name for name in names if name != _MANIFEST]
    activation = {name for name in payload if name.startswith("activation/")}
    released = {name for name in payload if name.startswith("release/")}
    if activation != {_ACTIVATION} or released != release:
        raise BackupVerificationError(_ERROR)
    if "capsule/migration-capsule.json" not in payload:
        raise BackupVerificationError(_ERROR)
    if "snapshot/backup-current.json" not in payload:
        raise BackupVerificationError(_ERROR)
    return [
        {"path": name, "size": size, "sha256": digest}
        for name in sorted(payload)
        for size, digest in [fingerprint_regular_file(root / name)]
    ]


def _manifest_schema(payload: dict[str, Any]) -> None:
    if set(payload) != _KEYS or payload["kind"] != _KIND:
        raise BackupVerificationError(_ERROR)
    if type(payload["graph_schema_version"]) is not int or payload["graph_schema_version"] != 1:
        raise BackupVerificationError(_ERROR)
    if type(payload["snapshot_schema_version"]) is not int:
        raise BackupVerificationError(_ERROR)
    if type(payload["snapshot_revision"]) is not int:
        raise BackupVerificationError(_ERROR)
    if not isinstance(payload["snapshot_backup_id"], str) or not payload["snapshot_backup_id"]:
        raise BackupVerificationError(_ERROR)


def _roles(basename: str) -> dict[str, str]:
    return {
        "activation": _ACTIVATION,
        "release_wheel": f"release/{basename}",
        "release_lock": _LOCK,
        "release_binding": _BINDING,
        "migration_capsule": "capsule",
        "snapshot": "snapshot",
    }


def _require(ok: bool) -> None:
    if not ok:
        raise BackupVerificationError(_ERROR)
