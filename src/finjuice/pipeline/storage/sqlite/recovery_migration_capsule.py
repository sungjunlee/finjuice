"""Preserve an inactive migration candidate and its reconstructible capture proof."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.backup.manifest import compute_manifest_digest, validate_manifest_structure
from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.migration.verify import verify_migration
from finjuice.pipeline.storage.authority import ActivationEvidence
from finjuice.pipeline.storage.sqlite.backup_io import (
    checked_directories,
    copy_regular_file,
    fingerprint_regular_file,
    read_regular_bytes,
)
from finjuice.pipeline.storage.sqlite.backup_publication import fsync_attempt_tree
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError

Semantics = Literal["raw_file_sha256", "canonical_manifest_digest"]
_MANIFEST = "migration-capsule.json"
_PROOFS = {
    "finjuice.sqlite3",
    "manifests/migration-manifest.json",
    "manifests/plan-evidence.json",
    "FINJUICE_MIGRATION_COMPLETE",
}
_ERROR = "Migration capsule proof or immutable source evidence could not be verified."


@dataclass(frozen=True)
class ExpectedMigrationCapsule:
    """Independent manifest identities with mandatory, explicit digest semantics."""

    activation_evidence: ActivationEvidence
    migration_semantics: Semantics
    pre_cutover_semantics: Semantics

    def __post_init__(self) -> None:
        allowed = {"raw_file_sha256", "canonical_manifest_digest"}
        if self.migration_semantics not in allowed or self.pre_cutover_semantics not in allowed:
            raise BackupVerificationError(_ERROR)


@dataclass(frozen=True)
class MigrationCapsuleReceipt:
    """Content-free receipt; raw and canonical digests are distinct lowercase hex values."""

    migration_raw_sha256: str
    migration_canonical_digest: str
    pre_cutover_raw_sha256: str
    pre_cutover_canonical_digest: str
    migration_semantics: Semantics
    pre_cutover_semantics: Semantics
    file_count: int
    capsule_digest: str


def capture_migration_capsule(
    candidate: Path, destination: Path, expected: ExpectedMigrationCapsule
) -> MigrationCapsuleReceipt:
    """Copy only an immutable baseline into a fresh, durably published capsule."""
    staging = None
    owned = None
    try:
        source, target = Path(os.path.abspath(candidate)), Path(os.path.abspath(destination))
        source_identity = checked_directories(source)
        parent_identity = checked_directories(target.parent)
        _inactive_path(source)
        if target == source or target.is_relative_to(source) or source.is_relative_to(target):
            raise BackupVerificationError(_ERROR)
        if os.path.lexists(target):
            raise BackupVerificationError(_ERROR)
        staging = Path(tempfile.mkdtemp(prefix=".capsule-", dir=target.parent))
        owned = checked_directories(staging)
        copied = staging / "candidate"
        copied.mkdir(mode=0o700)
        receipt = _copy_candidate(source, copied, expected)
        files = _files(staging)
        body: dict[str, Any] = {
            "capsule_schema_version": 1,
            "receipt": asdict(receipt),
            "files": files,
        }
        body["receipt"].pop("capsule_digest")
        _write(staging / _MANIFEST, _canonical({**body, "capsule_digest": _sha(_canonical(body))}))
        result = verify_migration_capsule(staging, expected)
        fsync_attempt_tree(staging)
        if (
            checked_directories(source) != source_identity
            or checked_directories(target.parent) != parent_identity
            or checked_directories(staging) != owned
        ):
            raise BackupVerificationError(_ERROR)
        rename_exclusive(staging, target)
        staging = None
        _fsync_directory(target.parent)
        return result
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    finally:
        if staging is not None and owned is not None:
            try:
                if checked_directories(staging) == owned:
                    shutil.rmtree(staging)
            except (OSError, BackupVerificationError):
                pass


def _copy_candidate(
    source: Path, copied: Path, expected: ExpectedMigrationCapsule
) -> MigrationCapsuleReceipt:
    for relative in sorted(_PROOFS):
        _copy(source, copied, relative)
    proofs = _json(read_regular_bytes(copied / "manifests/migration-manifest.json"))
    if (
        "sha256:" + fingerprint_regular_file(copied / "finjuice.sqlite3")[1]
        != proofs["database_digest"]
    ):
        raise BackupVerificationError(_ERROR)
    objects = _object_inventory(copied)
    _tree(source, _PROOFS | set(objects))
    for relative, identity in objects.items():
        if _copy(source, copied, relative) != identity:
            raise BackupVerificationError(_ERROR)
        os.chmod(copied / relative, 0o444)
    _tree(source, _PROOFS | set(objects))
    return _verify_candidate(copied, expected)


def verify_migration_capsule(
    capsule: Path, expected: ExpectedMigrationCapsule
) -> MigrationCapsuleReceipt:
    """Replay copied candidate proof, reconstruct full capture and verify semantic parity."""
    try:
        root = Path(os.path.abspath(capsule))
        checked_directories(root)
        raw = read_regular_bytes(root / _MANIFEST)
        payload = _json(raw)
        if (
            set(payload) != {"capsule_schema_version", "receipt", "files", "capsule_digest"}
            or type(payload["capsule_schema_version"]) is not int
            or payload["capsule_schema_version"] != 1
        ):
            raise BackupVerificationError(_ERROR)
        body = {k: v for k, v in payload.items() if k != "capsule_digest"}
        if payload["capsule_digest"] != _sha(_canonical(body)) or _canonical(
            payload["files"]
        ) != _canonical(_files(root)):
            raise BackupVerificationError(_ERROR)
        receipt = _verify_candidate(root / "candidate", expected)
        recorded = asdict(receipt)
        recorded.pop("capsule_digest")
        if (
            _canonical(recorded) != _canonical(payload["receipt"])
            or read_regular_bytes(root / _MANIFEST) != raw
        ):
            raise BackupVerificationError(_ERROR)
        return MigrationCapsuleReceipt(**{**recorded, "capsule_digest": payload["capsule_digest"]})
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _verify_candidate(
    candidate: Path, expected: ExpectedMigrationCapsule
) -> MigrationCapsuleReceipt:
    _inactive_path(candidate)
    objects = _object_inventory(candidate)
    _tree(candidate, _PROOFS | set(objects))
    verify_migration(candidate)
    raw = read_regular_bytes(candidate / "manifests/migration-manifest.json")
    manifest = _json(raw)
    capture_digest = manifest["capture_object_digest"].removeprefix("sha256:")
    capture_path = candidate / f"objects/sha256/{capture_digest[:2]}/{capture_digest}"
    capture_raw = read_regular_bytes(capture_path)
    capture = _json(capture_raw)
    validate_manifest_structure(capture)
    if (
        capture != manifest["capture"]
        or _sha(capture_raw) != capture_digest
        or compute_manifest_digest(capture) != capture["canonical_digest"]
    ):
        raise BackupVerificationError(_ERROR)
    migration_canonical = manifest["canonical_digest"].removeprefix("sha256:")
    capture_canonical = capture["canonical_digest"].removeprefix("sha256:")
    migration = (
        _sha(raw) if expected.migration_semantics == "raw_file_sha256" else migration_canonical
    )
    pre_cutover = (
        _sha(capture_raw)
        if expected.pre_cutover_semantics == "raw_file_sha256"
        else capture_canonical
    )
    evidence = expected.activation_evidence
    if (
        migration != evidence.verified_migration_manifest_sha256
        or pre_cutover != evidence.verified_pre_cutover_backup_manifest_sha256
    ):
        raise BackupVerificationError(_ERROR)
    return MigrationCapsuleReceipt(
        _sha(raw),
        migration_canonical,
        _sha(capture_raw),
        capture_canonical,
        expected.migration_semantics,
        expected.pre_cutover_semantics,
        len(_PROOFS) + len(objects),
        "",
    )


def _object_inventory(candidate: Path) -> dict[str, tuple[int, str]]:
    _inactive_path(candidate)
    database = candidate / "finjuice.sqlite3"
    proof = _json(read_regular_bytes(candidate / "manifests/migration-manifest.json"))
    if "sha256:" + fingerprint_regular_file(database)[1] != proof["database_digest"]:
        raise BackupVerificationError(_ERROR)
    uri = database.as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT object_path,byte_length,digest_hex FROM source_artifacts ORDER BY object_path"
        ).fetchall()
    finally:
        connection.close()
    result = {}
    for path, size, digest in rows:
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or path != f"objects/sha256/{digest[:2]}/{digest}"
            or type(size) is not int
            or size < 0
            or path in result
        ):
            raise BackupVerificationError(_ERROR)
        result[path] = (size, digest)
    return result


def _inactive_path(path: Path) -> None:
    if any(part.casefold() == ".finjuice" for part in path.parts):
        raise BackupVerificationError(_ERROR)
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.lexists(path / ("finjuice.sqlite3" + suffix)):
            raise BackupVerificationError(_ERROR)


def _tree(root: Path, files: set[str]) -> None:
    prefix = "candidate/" if any(name.startswith("candidate/") for name in files) else ""
    dirs = {prefix + name for name in ("objects", "objects/sha256", "manifests", "derived")}
    for name in files:
        dirs.update(str(p) for p in Path(name).parents if str(p) != ".")
    seen = set()
    pending = [root]
    while pending:
        parent = pending.pop()
        checked_directories(parent)
        for path in parent.iterdir():
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode) and relative in dirs:
                pending.append(path)
            elif stat.S_ISREG(mode) and relative in files:
                seen.add(relative)
            else:
                raise BackupVerificationError(_ERROR)
    if seen != files:
        raise BackupVerificationError(_ERROR)


def _files(root: Path) -> list[dict[str, Any]]:
    candidate = root / "candidate"
    objects = _object_inventory(candidate)
    expected = {"candidate/" + name for name in _PROOFS | set(objects)}
    root_files = expected | ({_MANIFEST} if os.path.lexists(root / _MANIFEST) else set())
    _tree(root, root_files)
    return [
        {"path": name, "size": size, "sha256": digest}
        for name in sorted(expected)
        for size, digest in [fingerprint_regular_file(root / name)]
    ]


def _copy(source: Path, target: Path, relative: str) -> tuple[int, str]:
    destination = target / relative
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return copy_regular_file(source / relative, destination)


def _write(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise BackupVerificationError(_ERROR)
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise BackupVerificationError(_ERROR)
            result[key] = value
        return result

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise BackupVerificationError(_ERROR)
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
