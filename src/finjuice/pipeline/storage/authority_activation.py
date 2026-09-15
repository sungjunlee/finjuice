"""Activation record types and JSON read/verify helpers.

Owns evidence/tuple identities, bounded activation-file reads, payload
validation, and external-evidence comparison. Public names stay importable
from :mod:`finjuice.pipeline.storage.authority`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityIntegrityError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVATION_SCHEMA_VERSION = 1
_MAX_ACTIVATION_BYTES = 64 * 1024


@dataclass(frozen=True)
class ActivationEvidence:
    """Release and verified-manifest identities established outside the pointer."""

    installed_release_version: str
    installed_release_artifact_sha256: str
    verified_migration_manifest_sha256: str
    verified_pre_cutover_backup_manifest_sha256: str

    def __post_init__(self) -> None:
        if not self.installed_release_version:
            raise ValueError("Installed release version must be explicit.")
        for digest in (
            self.installed_release_artifact_sha256,
            self.verified_migration_manifest_sha256,
            self.verified_pre_cutover_backup_manifest_sha256,
        ):
            if _DIGEST_RE.fullmatch(digest) is None:
                raise ValueError("Activation evidence digests must be lowercase SHA-256 text.")


@dataclass(frozen=True)
class ActivationTuple:
    """Immutable activation-time release and dataset binding."""

    release_version: str
    release_artifact_sha256: str
    dataset_generation: str
    sqlite_schema_version: int
    dataset_revision: int
    migration_manifest_sha256: str
    pre_cutover_backup_manifest_sha256: str
    activated_at: str


def _read_activation(path: Path) -> ActivationTuple:
    raw = _read_activation_bytes(path)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityIntegrityError("Activation record is not valid JSON.") from exc
    _validate_activation_payload(payload)
    return ActivationTuple(
        release_version=payload["release_version"],
        release_artifact_sha256=payload["release_artifact_sha256"],
        dataset_generation=payload["dataset_generation"],
        sqlite_schema_version=payload["sqlite_schema_version"],
        dataset_revision=payload["dataset_revision"],
        migration_manifest_sha256=payload["migration_manifest_sha256"],
        pre_cutover_backup_manifest_sha256=payload["pre_cutover_backup_manifest_sha256"],
        activated_at=payload["activated_at"],
    )


def _read_activation_bytes(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        _assert_no_symlink_ancestors(path)
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        entry = os.fstat(descriptor)
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise AuthorityIntegrityError("Activation record is not a safe regular file.")
        if entry.st_size > _MAX_ACTIVATION_BYTES:
            raise AuthorityIntegrityError("Activation record exceeds the size limit.")
        raw = _read_bounded(descriptor)
        after = os.fstat(descriptor)
        current_path = path.lstat()
    except (OSError, ValueError, RepositoryPathError) as exc:
        raise AuthorityIntegrityError("Activation record could not be read safely.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(raw) > _MAX_ACTIVATION_BYTES:
        raise AuthorityIntegrityError("Activation record exceeds the size limit.")
    if (entry.st_dev, entry.st_ino, entry.st_size, entry.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise AuthorityIntegrityError("Activation record changed while being read.")
    if (entry.st_dev, entry.st_ino) != (current_path.st_dev, current_path.st_ino):
        raise AuthorityIntegrityError("Activation record changed while being read.")
    return raw


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = _MAX_ACTIVATION_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(8192, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _validate_activation_payload(payload: Any) -> None:
    required = {
        "activation_schema_version",
        "release_version",
        "release_artifact_sha256",
        "dataset_generation",
        "sqlite_schema_version",
        "dataset_revision",
        "migration_manifest_sha256",
        "pre_cutover_backup_manifest_sha256",
        "activated_at",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise AuthorityIntegrityError("Activation record fields are invalid.")
    if payload.get("activation_schema_version") != _ACTIVATION_SCHEMA_VERSION:
        raise AuthorityIntegrityError("Activation record schema is unsupported.")
    text_fields = required - {
        "activation_schema_version",
        "sqlite_schema_version",
        "dataset_revision",
    }
    if any(not isinstance(payload.get(field), str) or not payload[field] for field in text_fields):
        raise AuthorityIntegrityError("Activation record text fields are invalid.")
    if not _is_non_negative_int(payload["sqlite_schema_version"]) or not _is_non_negative_int(
        payload["dataset_revision"]
    ):
        raise AuthorityIntegrityError("Activation schema and revision fields are invalid.")
    try:
        validate_entity_id(payload["dataset_generation"])
    except ValueError as exc:
        raise AuthorityIntegrityError("Activation generation is invalid.") from exc
    for field in (
        "release_artifact_sha256",
        "migration_manifest_sha256",
        "pre_cutover_backup_manifest_sha256",
    ):
        if _DIGEST_RE.fullmatch(payload[field]) is None:
            raise AuthorityIntegrityError("Activation record contains an invalid digest.")


def _is_non_negative_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _verify_external_evidence(
    activation: ActivationTuple,
    evidence: ActivationEvidence,
) -> None:
    expected = (
        evidence.installed_release_version,
        evidence.installed_release_artifact_sha256,
        evidence.verified_migration_manifest_sha256,
        evidence.verified_pre_cutover_backup_manifest_sha256,
    )
    actual = (
        activation.release_version,
        activation.release_artifact_sha256,
        activation.migration_manifest_sha256,
        activation.pre_cutover_backup_manifest_sha256,
    )
    if actual != expected:
        raise AuthorityIntegrityError(
            "Activation record does not match installed release and verified manifest evidence."
        )
