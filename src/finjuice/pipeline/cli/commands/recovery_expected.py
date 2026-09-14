"""Load independently enrolled ExpectedRecoveryGraph JSON.

Operators retain this document separately. The loader never reads a candidate,
bundle, or live activation pointer to fill missing fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.authority import ActivationEvidence
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.recovery_bundle import ExpectedRecoveryGraph
from finjuice.pipeline.storage.sqlite.recovery_migration_capsule import ExpectedMigrationCapsule
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import TrustedReleaseBinding

_ERROR = "Independently retained recovery expectations could not be verified."
_GRAPH_KEYS = {
    "activation_evidence",
    "activation_sha256",
    "release",
    "capsule",
    "wheel_basename",
}
_EVIDENCE_KEYS = {
    "installed_release_version",
    "installed_release_artifact_sha256",
    "verified_migration_manifest_sha256",
    "verified_pre_cutover_backup_manifest_sha256",
}
_RELEASE_KEYS = {"binding_sha256", "activation_evidence"}
_CAPSULE_KEYS = {
    "activation_evidence",
    "migration_semantics",
    "pre_cutover_semantics",
}
_SEMANTICS = {"raw_file_sha256", "canonical_manifest_digest"}


def load_expected_recovery_graph(path: Path) -> ExpectedRecoveryGraph:
    """Parse one regular-file expectation document into the capture DTO."""
    try:
        payload = _object(read_regular_bytes(path), _GRAPH_KEYS)
        evidence = _evidence(payload["activation_evidence"])
        release = _object(payload["release"], _RELEASE_KEYS)
        capsule = _object(payload["capsule"], _CAPSULE_KEYS)
        wheel = payload["wheel_basename"]
        sha = payload["activation_sha256"]
        if type(wheel) is not str or type(sha) is not str:
            raise BackupVerificationError(_ERROR)
        for key in ("migration_semantics", "pre_cutover_semantics"):
            if capsule[key] not in _SEMANTICS or type(capsule[key]) is not str:
                raise BackupVerificationError(_ERROR)
        return ExpectedRecoveryGraph(
            evidence,
            sha,
            TrustedReleaseBinding(
                release["binding_sha256"],
                _evidence(release["activation_evidence"]),
            ),
            ExpectedMigrationCapsule(
                _evidence(capsule["activation_evidence"]),
                capsule["migration_semantics"],
                capsule["pre_cutover_semantics"],
            ),
            wheel,
        )
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        payload = json.loads(bytes(value).decode("utf-8"), object_pairs_hook=_unique)
    else:
        payload = value
    if not isinstance(payload, dict) or set(payload) != keys:
        raise BackupVerificationError(_ERROR)
    return payload


def _evidence(value: object) -> ActivationEvidence:
    payload = _object(value, _EVIDENCE_KEYS)
    if any(type(payload[key]) is not str for key in _EVIDENCE_KEYS):
        raise BackupVerificationError(_ERROR)
    return ActivationEvidence(
        payload["installed_release_version"],
        payload["installed_release_artifact_sha256"],
        payload["verified_migration_manifest_sha256"],
        payload["verified_pre_cutover_backup_manifest_sha256"],
    )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise BackupVerificationError(_ERROR)
        document[key] = value
    return document
