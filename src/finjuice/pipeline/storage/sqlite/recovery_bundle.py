"""Capture and independently verify one local recovery graph.

This helper returns a local graph verification receipt. It does not prove
off-device copy, encryption, key recovery, capacity, RPO/RTO, wheel installation,
or GC deletion. Managed store capture, verify, restore, and prune coordinate
through the initialized store lease; this helper still verifies one graph body.

Graph inventory and manifest-schema helpers live in
:mod:`finjuice.pipeline.storage.sqlite.recovery_bundle_manifest` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    ActivationEvidenceProvider,
    ActivationTuple,
    AuthorityPaths,
    RepositoryAuthority,
    read_activation,
    resolve_storage_authority,
    shared_write_lease,
)
from finjuice.pipeline.storage.sqlite.backup import (
    BackupResult,
    RestoreResult,
    create_backup,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.backup_io import (
    checked_directories,
    read_regular_bytes,
)
from finjuice.pipeline.storage.sqlite.backup_publication import fsync_attempt_tree
from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _ACTIVATION as _ACTIVATION,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _BINDING as _BINDING,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _KIND as _KIND,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _LOCK as _LOCK,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _MANIFEST as _MANIFEST,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _files as _files,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _manifest_schema as _manifest_schema,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle_manifest import (
    _roles as _roles,
)
from finjuice.pipeline.storage.sqlite.recovery_migration_capsule import (
    ExpectedMigrationCapsule,
    capture_migration_capsule,
    verify_migration_capsule,
)
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import (
    ReleaseArtifactPaths,
    TrustedReleaseBinding,
    VerifiedReleaseArtifacts,
    verify_release_artifacts,
)
from finjuice.pipeline.storage.sqlite.schema import (
    SQLITE_SCHEMA_VERSION,
    RepositoryInfo,
    inspect_repository,
)

_ERROR = "Local recovery graph proof or independently trusted evidence could not be verified."
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TUPLE_KEYS = {
    "release_version",
    "release_artifact_sha256",
    "dataset_generation",
    "sqlite_schema_version",
    "dataset_revision",
    "migration_manifest_sha256",
    "pre_cutover_backup_manifest_sha256",
    "activated_at",
}
_Owned = tuple[tuple[Path, int, int], ...]


@dataclass(frozen=True)
class RecoveryCaptureInput:
    """Operator-selected live tree, artifacts and destination; paths are not trust evidence."""

    data_dir: Path
    destination: Path
    evidence_provider: ActivationEvidenceProvider
    release_paths: ReleaseArtifactPaths
    migration_candidate: Path


@dataclass(frozen=True)
class ExpectedRecoveryGraph:
    """Caller-retained expectations; never derived from the live pointer or bundle body."""

    activation_evidence: ActivationEvidence
    activation_sha256: str
    release: TrustedReleaseBinding
    capsule: ExpectedMigrationCapsule
    wheel_basename: str

    def __post_init__(self) -> None:
        if not isinstance(self.activation_sha256, str) or not _DIGEST.fullmatch(
            self.activation_sha256
        ):
            raise BackupVerificationError(_ERROR)
        if self.release.activation_evidence != self.activation_evidence:
            raise BackupVerificationError(_ERROR)
        if self.capsule.activation_evidence != self.activation_evidence:
            raise BackupVerificationError(_ERROR)
        _wheel_basename(self.wheel_basename, self.activation_evidence.installed_release_version)


@dataclass(frozen=True)
class RecoveryGraphReceipt:
    """Local graph verification receipt; not an off-device or operational-complete verdict."""

    kind: str
    graph_digest: str
    activation_sha256: str
    wheel_basename: str
    snapshot_generation: str
    snapshot_schema_version: int
    snapshot_revision: int
    activation_revision: int
    snapshot_backup_id: str
    snapshot_manifest_digest: str
    file_count: int
    capsule_digest: str

    def to_dict(self) -> dict[str, Any]:
        """Return the privacy-safe receipt without filesystem paths or source bytes."""
        return asdict(self)


def capture_recovery_bundle(
    source: RecoveryCaptureInput, expected: ExpectedRecoveryGraph
) -> RecoveryGraphReceipt:
    """Hold the shared lease, copy retained buffers, and publish a fresh local graph."""
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    staging = None
    owned = None
    scratch = None
    scratch_owned = None
    try:
        data_dir, destination, candidate = _roots(source)
        with managed_read_lease(destination):
            identities = (
                checked_directories(destination.parent),
                checked_directories(data_dir),
                checked_directories(candidate),
            )
            paths = AuthorityPaths.for_data_dir(data_dir)
            with shared_write_lease(paths):
                staging, owned, scratch, scratch_owned, receipt = _capture_locked(
                    source, expected, paths
                )
                _admit(data_dir, source.evidence_provider, expected)
                if (
                    checked_directories(destination.parent) != identities[0]
                    or checked_directories(data_dir) != identities[1]
                    or checked_directories(candidate) != identities[2]
                    or checked_directories(staging) != owned
                ):
                    raise BackupVerificationError(_ERROR)
                rename_exclusive(staging, destination)
                staging = None
                _fsync_directory(destination.parent)
                return receipt
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    finally:
        _discard(staging, owned)
        _discard(scratch, scratch_owned)


def verify_recovery_bundle(bundle: Path, expected: ExpectedRecoveryGraph) -> RecoveryGraphReceipt:
    """Verify one published graph using only the bundle and caller-trusted expectations."""
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    try:
        with managed_read_lease(bundle):
            return _verify_unlocked(bundle, expected)
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _verify_unlocked(bundle: Path, expected: ExpectedRecoveryGraph) -> RecoveryGraphReceipt:
    try:
        root = Path(os.path.abspath(bundle))
        checked_directories(root)
        raw = read_regular_bytes(root / _MANIFEST)
        payload = _json(raw)
        _manifest_schema(payload)
        body = {key: payload[key] for key in payload if key != "graph_digest"}
        files = _files(root, expected.wheel_basename)
        if payload["graph_digest"] != _sha(_canonical(body)) or _canonical(
            payload["files"]
        ) != _canonical(files):
            raise BackupVerificationError(_ERROR)
        activation = _verify_activation(root, expected, payload)
        _verify_release(root, expected)
        capsule = verify_migration_capsule(root / "capsule", expected.capsule)
        info, backup_id, manifest_digest = _verify_snapshot(root, activation, payload)
        _require(read_regular_bytes(root / _MANIFEST) == raw)
        generation, revision = _generation_revision(info)
        return RecoveryGraphReceipt(
            kind="local_graph_verified",
            graph_digest=payload["graph_digest"],
            activation_sha256=expected.activation_sha256,
            wheel_basename=expected.wheel_basename,
            snapshot_generation=generation,
            snapshot_schema_version=info.schema_version,
            snapshot_revision=revision,
            activation_revision=activation.dataset_revision,
            snapshot_backup_id=backup_id,
            snapshot_manifest_digest=manifest_digest,
            file_count=len(files),
            capsule_digest=capsule.capsule_digest,
        )
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _capture_locked(
    source: RecoveryCaptureInput,
    expected: ExpectedRecoveryGraph,
    paths: AuthorityPaths,
) -> tuple[Path, _Owned, Path, _Owned, RecoveryGraphReceipt]:
    data_dir = Path(os.path.abspath(source.data_dir))
    destination = Path(os.path.abspath(source.destination))
    candidate = Path(os.path.abspath(source.migration_candidate))
    raw, activation = _admit(data_dir, source.evidence_provider, expected)
    artifacts = verify_release_artifacts(source.release_paths, expected.release)
    _require(Path(source.release_paths.wheel).name == expected.wheel_basename)
    staging = Path(tempfile.mkdtemp(prefix=".recovery-graph-", dir=destination.parent))
    owned = checked_directories(staging)
    scratch = None
    scratch_owned = None
    try:
        _materialize(staging, raw, artifacts, expected.wheel_basename)
        capture_migration_capsule(candidate, staging / "capsule", expected.capsule)
        backup = create_backup(
            paths.generation(activation.dataset_generation).database, staging / "snapshot"
        )
        scratch = Path(tempfile.mkdtemp(prefix=".recovery-scratch-", dir=destination.parent))
        scratch_owned = checked_directories(scratch)
        restored = restore_backup(staging / "snapshot", scratch / "generation")
        info = inspect_repository(restored.database)
        _snapshot_agrees(info, activation, backup, restored)
        receipt = _seal(staging, expected, activation, info, backup.backup_id)
        later_raw, later = _admit(data_dir, source.evidence_provider, expected)
        _require(later_raw == raw and later == activation)
        fsync_attempt_tree(staging)
        return staging, owned, scratch, scratch_owned, receipt
    except Exception:
        _discard(staging, owned)
        _discard(scratch, scratch_owned)
        raise


def _roots(source: RecoveryCaptureInput) -> tuple[Path, Path, Path]:
    data_dir = Path(os.path.abspath(source.data_dir))
    destination = Path(os.path.abspath(source.destination))
    candidate = Path(os.path.abspath(source.migration_candidate))
    for path in (data_dir, candidate, source.release_paths.wheel):
        _separate(destination, path)
    if os.path.lexists(destination) or any(
        part.casefold() == ".finjuice" for part in destination.parts
    ):
        raise BackupVerificationError(_ERROR)
    checked_directories(data_dir)
    checked_directories(candidate)
    checked_directories(destination.parent)
    return data_dir, destination, candidate


def _admit(
    data_dir: Path,
    provider: ActivationEvidenceProvider,
    expected: ExpectedRecoveryGraph,
) -> tuple[bytes, ActivationTuple]:
    paths = AuthorityPaths.for_data_dir(data_dir)
    dispatch = resolve_storage_authority(data_dir, provider)
    _require(isinstance(dispatch.authority, RepositoryAuthority))
    _require(dispatch.evidence == expected.activation_evidence)
    first = read_regular_bytes(paths.activation)
    activation = read_activation(paths, expected.activation_evidence)
    second = read_regular_bytes(paths.activation)
    parsed = _activation_tuple(first)
    _require(first == second and parsed == activation)
    _require(_sha(first) == expected.activation_sha256)
    _require(_evidence_matches(expected.activation_evidence, activation))
    return first, activation


def _materialize(
    staging: Path, raw: bytes, artifacts: VerifiedReleaseArtifacts, basename: str
) -> None:
    (staging / "activation").mkdir(mode=0o700)
    (staging / "release").mkdir(mode=0o700)
    _write(staging / _ACTIVATION, raw)
    _write(staging / "release" / basename, artifacts.wheel_bytes)
    _write(staging / _LOCK, artifacts.dependency_lock_bytes)
    _write(staging / _BINDING, artifacts.binding_bytes)


def _seal(
    staging: Path,
    expected: ExpectedRecoveryGraph,
    activation: ActivationTuple,
    info: RepositoryInfo,
    backup_id: str,
) -> RecoveryGraphReceipt:
    files = _files(staging, expected.wheel_basename)
    body: dict[str, Any] = {
        "graph_schema_version": 1,
        "kind": _KIND,
        "roles": _roles(expected.wheel_basename),
        "activation": asdict(activation),
        "activation_sha256": expected.activation_sha256,
        "snapshot_generation": info.dataset_generation,
        "snapshot_schema_version": info.schema_version,
        "snapshot_revision": info.dataset_revision,
        "snapshot_backup_id": backup_id,
        "wheel_basename": expected.wheel_basename,
        "files": files,
    }
    _write(staging / _MANIFEST, _canonical({**body, "graph_digest": _sha(_canonical(body))}))
    return verify_recovery_bundle(staging, expected)


def _snapshot_agrees(
    info: RepositoryInfo,
    activation: ActivationTuple,
    backup: BackupResult,
    restored: RestoreResult,
) -> None:
    _require(restored.verified)
    generation, revision = _generation_revision(info)
    _require(generation == activation.dataset_generation)
    _require(info.schema_version == activation.sqlite_schema_version)
    _require(info.schema_version == SQLITE_SCHEMA_VERSION)
    _require(revision >= activation.dataset_revision)
    _require(generation == backup.source_generation)
    _require(backup.source_generation == restored.source_generation)
    _require(revision == backup.dataset_revision)
    _require(backup.dataset_revision == restored.dataset_revision)


def _verify_activation(
    root: Path, expected: ExpectedRecoveryGraph, payload: dict[str, Any]
) -> ActivationTuple:
    activation_raw = read_regular_bytes(root / _ACTIVATION)
    activation = _activation_tuple(activation_raw)
    _require(_sha(activation_raw) == expected.activation_sha256)
    _require(_evidence_matches(expected.activation_evidence, activation))
    _require(_canonical(payload["activation"]) == _canonical(asdict(activation)))
    _require(payload["activation_sha256"] == expected.activation_sha256)
    _require(payload["wheel_basename"] == expected.wheel_basename)
    _require(payload["roles"] == _roles(expected.wheel_basename))
    return activation


def _verify_release(root: Path, expected: ExpectedRecoveryGraph) -> None:
    verify_release_artifacts(
        ReleaseArtifactPaths(
            root / "release" / expected.wheel_basename,
            root / _LOCK,
            root / _BINDING,
        ),
        expected.release,
    )


def _verify_snapshot(
    root: Path, activation: ActivationTuple, payload: dict[str, Any]
) -> tuple[RepositoryInfo, str, str]:
    selected, snapshot, layout = resolve_backup_input(root / "snapshot")
    _require(snapshot.backup_id == payload["snapshot_backup_id"])
    _require(layout == "attempt" and selected.parent.name == "attempts")
    scratch = Path(tempfile.mkdtemp(prefix=".recovery-verify-", dir=root.parent))
    owned = checked_directories(scratch)
    try:
        restored = restore_backup(root / "snapshot", scratch / "generation")
        _require(restored.manifest_digest == snapshot.manifest_digest)
        info = inspect_repository(
            restored.database, expected_schema_version=activation.sqlite_schema_version
        )
        generation, revision = _generation_revision(info)
        _require(generation == activation.dataset_generation)
        _require(info.schema_version == activation.sqlite_schema_version)
        _require(revision >= activation.dataset_revision)
        _require(generation == payload["snapshot_generation"])
        _require(payload["snapshot_generation"] == snapshot.source_generation)
        _require(info.schema_version == payload["snapshot_schema_version"])
        _require(revision == payload["snapshot_revision"])
        _require(payload["snapshot_revision"] == snapshot.dataset_revision)
        return info, snapshot.backup_id, restored.manifest_digest
    finally:
        _discard(scratch, owned)


def _activation_tuple(raw: bytes) -> ActivationTuple:
    payload = _json(raw)
    if "activation_schema_version" in payload:
        version = payload["activation_schema_version"]
        if type(version) is not int or version != 1:
            raise BackupVerificationError(_ERROR)
        payload = {
            key: value for key, value in payload.items() if key != "activation_schema_version"
        }
    if set(payload) != _TUPLE_KEYS:
        raise BackupVerificationError(_ERROR)
    schema_ok = type(payload["sqlite_schema_version"]) is int
    revision_ok = type(payload["dataset_revision"]) is int
    if not schema_ok or not revision_ok:
        raise BackupVerificationError(_ERROR)
    try:
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
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _generation_revision(info: RepositoryInfo) -> tuple[str, int]:
    generation = info.dataset_generation
    revision = info.dataset_revision
    if generation is None or revision is None:
        raise BackupVerificationError(_ERROR)
    return generation, revision


def _evidence_matches(evidence: ActivationEvidence, activation: ActivationTuple) -> bool:
    return (
        evidence.installed_release_version == activation.release_version
        and evidence.installed_release_artifact_sha256 == activation.release_artifact_sha256
        and evidence.verified_migration_manifest_sha256 == activation.migration_manifest_sha256
        and evidence.verified_pre_cutover_backup_manifest_sha256
        == activation.pre_cutover_backup_manifest_sha256
    )


def _wheel_basename(name: str, version: str) -> None:
    expected = f"finjuice-{version}-py3-none-any.whl"
    if name != expected or name != Path(name).name or "/" in name or "\\" in name:
        raise BackupVerificationError(_ERROR)


def _separate(left: Path, right: Path) -> None:
    first, second = Path(os.path.abspath(left)), Path(os.path.abspath(right))
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise BackupVerificationError(_ERROR)


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise BackupVerificationError(_ERROR)
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _discard(path: Path | None, owned: _Owned | None) -> None:
    if path is None or owned is None:
        return
    try:
        if checked_directories(path) == owned:
            shutil.rmtree(path)
    except (OSError, BackupVerificationError):
        pass


def _json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise BackupVerificationError(_ERROR)
            document[key] = value
        return document

    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(payload, dict):
        raise BackupVerificationError(_ERROR)
    return payload


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(ok: bool) -> None:
    if not ok:
        raise BackupVerificationError(_ERROR)
