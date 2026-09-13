"""Strict local evidence and physical-path guards for inactive restored copies."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from finjuice.pipeline.storage.sqlite.backup_io import checked_directories, read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import RepositoryBackupError


class InactiveRestoreError(RepositoryBackupError):
    """An independently bound inactive restore cannot be safely used."""

    reason = "inactive_restore_unavailable"

    def __init__(self) -> None:
        super().__init__("The inactive restored workspace could not be verified or used.")


@dataclass(frozen=True)
class RestoredWorkspaceReceipt:
    """Caller-retained evidence; a local descriptor alone does not grant admission."""

    workspace: Path
    descriptor_digest: str
    restore_id: str
    dataset_generation: str
    initial_dataset_revision: int
    sqlite_schema_version: int
    initial_database_digest: str
    source_manifest_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if key != "workspace"}


def descriptor_body(receipt: RestoredWorkspaceReceipt) -> dict[str, Any]:
    body = receipt.to_dict()
    body.pop("descriptor_digest")
    return {"descriptor_schema_version": 1, "generation_path": "generation", **body}


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def descriptor_digest(body: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()


def validate_receipt(receipt: RestoredWorkspaceReceipt) -> None:
    for value in (receipt.restore_id, receipt.dataset_generation):
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise InactiveRestoreError()
    for revision, minimum in (
        (receipt.initial_dataset_revision, 0),
        (receipt.sqlite_schema_version, 1),
    ):
        if type(revision) is not int or revision < minimum:
            raise InactiveRestoreError()
    for digest in (
        receipt.descriptor_digest,
        receipt.initial_database_digest,
        receipt.source_manifest_digest,
    ):
        if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
            raise InactiveRestoreError()
        if any(char not in "0123456789abcdef" for char in digest[7:]):
            raise InactiveRestoreError()
    if descriptor_digest(descriptor_body(receipt)) != receipt.descriptor_digest:
        raise InactiveRestoreError()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InactiveRestoreError()
        result[key] = value
    return result


def verify_descriptor(receipt: RestoredWorkspaceReceipt) -> None:
    control = receipt.workspace / "restore-control"
    if os.path.lexists(control / "retired.json"):
        raise InactiveRestoreError()
    raw = read_regular_bytes(control / "descriptor.json")
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    expected = {**descriptor_body(receipt), "descriptor_digest": receipt.descriptor_digest}
    # Equality alone accepts bool as int; canonical representation must also match.
    if not isinstance(payload, dict) or canonical_bytes(payload) != canonical_bytes(expected):
        raise InactiveRestoreError()


def path_identity(path: Path, *, directory: bool = False) -> tuple[int, int]:
    info = path.lstat()
    valid = (
        stat.S_ISDIR(info.st_mode)
        if directory
        else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    )
    if not valid or (directory and info.st_mode & 0o077):
        raise InactiveRestoreError()
    return info.st_dev, info.st_ino


def workspace_identity(workspace: Path) -> tuple[tuple[int, int], ...]:
    checked_directories(workspace)
    directories = (workspace, workspace / "restore-control", workspace / "generation")
    identity = tuple(path_identity(path, directory=True) for path in directories)
    database = workspace / "generation" / "finjuice.sqlite3"
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if os.path.lexists(sidecar):
            path_identity(sidecar)
    return (*identity, path_identity(database))


def write_durable(path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(canonical_bytes(payload))
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise InactiveRestoreError()
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
