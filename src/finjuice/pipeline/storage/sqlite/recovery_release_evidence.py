"""Verify exact release artifacts against independently supplied build evidence."""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.authority import ActivationEvidence
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError

_ERROR = "Release artifacts do not match independently trusted build evidence."
_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_BUILD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_KEYS = {
    "binding_schema_version",
    "package_name",
    "release_version",
    "release_artifact_sha256",
    "dependency_lock_sha256",
    "source_commit",
    "build_id",
}
_MAX_METADATA_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class TrustedReleaseBinding:
    """Independent input, never derived from the candidate binding or active pointer."""

    binding_sha256: str
    activation_evidence: ActivationEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.binding_sha256, str) or not _DIGEST.fullmatch(self.binding_sha256):
            raise BackupVerificationError(_ERROR)


@dataclass(frozen=True)
class ReleaseArtifactPaths:
    """Operator-selected regular files; paths are not trust evidence."""

    wheel: Path
    dependency_lock: Path
    binding: Path


@dataclass(frozen=True)
class VerifiedReleaseArtifacts:
    """Verified exact bytes for later publication, independent of subsequent path changes."""

    release_version: str
    release_artifact_sha256: str
    dependency_lock_sha256: str
    binding_sha256: str
    source_commit: str
    build_id: str
    wheel_bytes: bytes = field(repr=False)
    dependency_lock_bytes: bytes = field(repr=False)
    binding_bytes: bytes = field(repr=False)
    package_name: str = "finjuice"


def verify_release_artifacts(
    paths: ReleaseArtifactPaths, expected: TrustedReleaseBinding
) -> VerifiedReleaseArtifacts:
    """Read each input once and verify hashes, build binding, and wheel metadata.

    This does not install code, prove runtime compatibility, or authenticate the
    caller's independently supplied trust root.
    """
    try:
        binding_bytes = read_regular_bytes(paths.binding)
        binding_hash = _sha256(binding_bytes)
        if binding_hash != expected.binding_sha256:
            raise BackupVerificationError(_ERROR)
        binding = _binding(binding_bytes, expected.activation_evidence)
        wheel = read_regular_bytes(paths.wheel)
        lock = read_regular_bytes(paths.dependency_lock)
        if _sha256(wheel) != binding["release_artifact_sha256"]:
            raise BackupVerificationError(_ERROR)
        if _sha256(lock) != binding["dependency_lock_sha256"]:
            raise BackupVerificationError(_ERROR)
        _wheel(wheel, binding["release_version"])
        return VerifiedReleaseArtifacts(
            release_version=binding["release_version"],
            release_artifact_sha256=binding["release_artifact_sha256"],
            dependency_lock_sha256=binding["dependency_lock_sha256"],
            binding_sha256=binding_hash,
            source_commit=binding["source_commit"],
            build_id=binding["build_id"],
            wheel_bytes=wheel,
            dependency_lock_bytes=lock,
            binding_bytes=binding_bytes,
        )
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise BackupVerificationError(_ERROR)
        document[key] = value
    return document


def _binding(raw: bytes, evidence: ActivationEvidence) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(payload, dict) or set(payload) != _KEYS:
        raise BackupVerificationError(_ERROR)
    if type(payload["binding_schema_version"]) is not int or payload["binding_schema_version"] != 1:
        raise BackupVerificationError(_ERROR)
    if payload["package_name"] != "finjuice":
        raise BackupVerificationError(_ERROR)
    if payload["release_version"] != evidence.installed_release_version:
        raise BackupVerificationError(_ERROR)
    if payload["release_artifact_sha256"] != evidence.installed_release_artifact_sha256:
        raise BackupVerificationError(_ERROR)
    patterns = {"dependency_lock_sha256": _DIGEST, "source_commit": _COMMIT, "build_id": _BUILD}
    for key, pattern in patterns.items():
        if not isinstance(payload[key], str) or not pattern.fullmatch(payload[key]):
            raise BackupVerificationError(_ERROR)
    return payload


def _wheel(raw: bytes, version: str) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise BackupVerificationError(_ERROR)
        for entry in entries:
            _wheel_member(entry)
        metadata = [entry for entry in entries if entry.filename.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise BackupVerificationError(_ERROR)
        entry = metadata[0]
        if not re.fullmatch(r"finjuice-[^/]+\.dist-info/METADATA", entry.filename):
            raise BackupVerificationError(_ERROR)
        if entry.file_size > _MAX_METADATA_BYTES:
            raise BackupVerificationError(_ERROR)
        document = BytesParser(policy=default).parsebytes(archive.read(entry))
        if document.defects or document.get_all("Name") != ["finjuice"]:
            raise BackupVerificationError(_ERROR)
        if document.get_all("Version") != [version]:
            raise BackupVerificationError(_ERROR)


def _wheel_member(entry: zipfile.ZipInfo) -> None:
    _wheel_extra(entry.extra)
    name = entry.orig_filename
    parts = name.rstrip("/").split("/")
    if (
        name != entry.filename
        or not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"[A-Za-z]:", name)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise BackupVerificationError(_ERROR)
    mode = entry.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    allowed = {0, stat.S_IFDIR} if entry.is_dir() else {0, stat.S_IFREG}
    if file_type not in allowed:
        raise BackupVerificationError(_ERROR)


def _wheel_extra(extra: bytes) -> None:
    # Unicode path overrides are interpreted differently across supported Python versions.
    while extra:
        if len(extra) < 4:
            raise BackupVerificationError(_ERROR)
        field = int.from_bytes(extra[:2], "little")
        size = int.from_bytes(extra[2:4], "little")
        if field == 0x7075 or len(extra) < size + 4:
            raise BackupVerificationError(_ERROR)
        extra = extra[size + 4 :]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
