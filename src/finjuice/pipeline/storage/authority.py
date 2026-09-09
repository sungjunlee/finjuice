"""Fail-closed authority selection and the shared cutover coordination lease."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised by monkeypatch on non-Windows CI
    _fcntl = None  # type: ignore[assignment]

from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityConflictError,
    AuthorityIntegrityError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import (
    _assert_no_symlink_ancestors,
    _mkdir_checked,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION, inspect_repository

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVATION_SCHEMA_VERSION = 1
_MAX_ACTIVATION_BYTES = 64 * 1024
_DEFAULT_LEASE_TIMEOUT_MS = 5_000


@dataclass(frozen=True)
class AuthorityPaths:
    """Paths shared by repository writers and the future activation command."""

    control_root: Path
    generations_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_root", self.control_root.expanduser().absolute())
        object.__setattr__(self, "generations_root", self.generations_root.expanduser().absolute())

    @classmethod
    def for_data_dir(cls, data_dir: Path) -> "AuthorityPaths":
        """Return the stable control namespace beneath one configured data directory."""
        root = data_dir.expanduser().absolute() / ".finjuice"
        return cls(control_root=root / "authority", generations_root=root / "generations")

    @property
    def activation(self) -> Path:
        return self.control_root / "active.json"

    @property
    def coordination_lock(self) -> Path:
        return self.control_root / "coordination.lock"

    def generation(self, dataset_generation: str) -> GenerationPaths:
        validate_entity_id(dataset_generation)
        return GenerationPaths(self.generations_root / dataset_generation)


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


@dataclass(frozen=True)
class LegacyAuthority:
    """Authority state before an activation record exists."""

    kind: Literal["legacy"] = "legacy"


@dataclass(frozen=True)
class RepositoryAuthority:
    """Validated active SQLite generation and its activation-time baseline."""

    activation: ActivationTuple
    paths: GenerationPaths
    kind: Literal["repository"] = "repository"


StorageAuthority = LegacyAuthority | RepositoryAuthority


class CoordinationLease(AbstractContextManager["CoordinationLease"]):
    """Advisory lease shared by writers and exclusively held by activation/maintenance."""

    def __init__(
        self,
        paths: AuthorityPaths,
        *,
        exclusive: bool,
        timeout_ms: int = _DEFAULT_LEASE_TIMEOUT_MS,
    ) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms < 0:
            raise ValueError("Lease timeout must be a non-negative integer.")
        self._paths = paths
        self._exclusive = exclusive
        self._timeout_ms = timeout_ms
        self._descriptor: int | None = None

    def __enter__(self) -> "CoordinationLease":
        if _fcntl is None:
            raise AuthorityIntegrityError(
                "Authority coordination leases are unsupported on this platform."
            )
        try:
            _mkdir_checked(self._paths.control_root)
            _assert_no_symlink_ancestors(self._paths.coordination_lock, allow_missing=True)
        except Exception as exc:
            raise AuthorityIntegrityError("Authority coordination namespace is unsafe.") from exc
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self._paths.coordination_lock, flags, 0o600)
            entry = os.fstat(descriptor)
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
                raise AuthorityIntegrityError("Authority coordination lock is not a safe file.")
            os.fchmod(descriptor, 0o600)
            operation = _fcntl.LOCK_EX if self._exclusive else _fcntl.LOCK_SH
            deadline = time.monotonic() + self._timeout_ms / 1000
            while True:
                try:
                    _fcntl.flock(descriptor, operation | _fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise AuthorityConflictError(
                            "Authority coordination lease timed out."
                        ) from exc
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        except BaseException:
            if "descriptor" in locals():
                os.close(descriptor)
            raise
        self._descriptor = descriptor
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._descriptor is None:
            return
        try:
            assert _fcntl is not None
            _fcntl.flock(self._descriptor, _fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None


def shared_write_lease(
    paths: AuthorityPaths,
    *,
    timeout_ms: int = _DEFAULT_LEASE_TIMEOUT_MS,
) -> CoordinationLease:
    """Acquire the namespace that every legacy and repository write must hold."""
    return CoordinationLease(paths, exclusive=False, timeout_ms=timeout_ms)


def exclusive_maintenance_lease(
    paths: AuthorityPaths,
    *,
    timeout_ms: int = _DEFAULT_LEASE_TIMEOUT_MS,
) -> CoordinationLease:
    """Acquire the namespace reserved for activation and maintenance in #440."""
    return CoordinationLease(paths, exclusive=True, timeout_ms=timeout_ms)


def resolve_authority(paths: AuthorityPaths, evidence: ActivationEvidence) -> StorageAuthority:
    """Resolve legacy or repository authority without modifying the data tree."""
    activation_path = paths.activation
    if not activation_path.exists() and not activation_path.is_symlink():
        return LegacyAuthority()
    activation = _read_activation(activation_path)
    _verify_external_evidence(activation, evidence)
    generation_paths = paths.generation(activation.dataset_generation)
    info = inspect_repository(generation_paths.database)
    if info.schema_version != activation.sqlite_schema_version:
        raise AuthorityIntegrityError("Activation schema does not match its repository.")
    if info.schema_version != SQLITE_SCHEMA_VERSION:
        raise AuthorityIntegrityError("Activated schema is unsupported by this runtime.")
    if info.dataset_generation != activation.dataset_generation:
        raise AuthorityIntegrityError("Activation generation does not match its repository.")
    if info.dataset_revision is None or info.dataset_revision < activation.dataset_revision:
        raise AuthorityIntegrityError("Repository revision precedes its activation baseline.")
    return RepositoryAuthority(activation=activation, paths=generation_paths)


def read_activation(
    paths: AuthorityPaths,
    evidence: ActivationEvidence,
) -> ActivationTuple:
    """Re-read and externally verify a required activation record under a held lease."""
    if not paths.activation.exists() and not paths.activation.is_symlink():
        raise AuthorityIntegrityError(
            "Activation record disappeared while a writer held its lease."
        )
    activation = _read_activation(paths.activation)
    _verify_external_evidence(activation, evidence)
    return activation


def require_legacy_authority(
    paths: AuthorityPaths, evidence: ActivationEvidence
) -> LegacyAuthority:
    """Fail closed when a legacy writer is attempted after activation."""
    resolved = resolve_authority(paths, evidence)
    if not isinstance(resolved, LegacyAuthority):
        raise AuthorityConflictError("Legacy writes are fenced after repository activation.")
    return resolved


def require_repository_authority(
    paths: AuthorityPaths,
    evidence: ActivationEvidence,
) -> RepositoryAuthority:
    """Fail closed unless a verified repository generation is active."""
    resolved = resolve_authority(paths, evidence)
    if not isinstance(resolved, RepositoryAuthority):
        raise AuthorityConflictError("Repository writes require an activation record.")
    return resolved


def require_repository_binding(
    paths: AuthorityPaths,
    evidence: ActivationEvidence,
) -> RepositoryAuthority:
    """Resolve a verified pointer before SQLite performs writer-side crash recovery."""
    activation = read_activation(paths, evidence)
    if activation.sqlite_schema_version != SQLITE_SCHEMA_VERSION:
        raise AuthorityIntegrityError("Activated schema is unsupported by this runtime.")
    return RepositoryAuthority(
        activation=activation,
        paths=paths.generation(activation.dataset_generation),
    )


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
