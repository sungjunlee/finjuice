"""Pinned-root trusted-host launch path for the existing Typer CLI.

The independently supplied enrollment digest is the operator pin. Enrollment
bytes, ``active.json``, and the process environment cannot approve a root or
release. This module does not activate a host, mutate permissions, or change
ordinary ``finjuice`` CSV defaults.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    RepositoryAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityIntegrityError,
    BackupVerificationError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import (
    ReleaseArtifactPaths,
    TrustedReleaseBinding,
    VerifiedReleaseArtifacts,
    verify_release_artifacts,
)

_ERROR = "Trusted host enrollment could not be verified."
_DIGEST_ERROR = "The independently supplied enrollment digest does not match the enrollment file."
_ROOT_ERROR = "The command data directory is not the enrolled data root."
_CODE_ERROR = "Installed code does not match the approved release artifact."
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ENROLLMENT_KEYS = {
    "data_root",
    "activation_evidence",
    "release",
    "artifacts",
    "wheel_basename",
}
_EVIDENCE_KEYS = {
    "installed_release_version",
    "installed_release_artifact_sha256",
    "verified_migration_manifest_sha256",
    "verified_pre_cutover_backup_manifest_sha256",
}
_RELEASE_KEYS = {"binding_sha256", "activation_evidence"}
_ARTIFACT_KEYS = {"wheel", "dependency_lock", "binding"}
_ROOT_FLAGS = {"--version", "--verbose", "-v", "--no-filter", "--help", "-h"}
_HOST_COMMAND = "trusted-host"


@dataclass(frozen=True)
class BoundRootActivationEvidenceProvider:
    """Evidence that is valid only for one independently enrolled data root."""

    data_root: Path
    evidence: ActivationEvidence

    def evidence_for(self, paths: AuthorityPaths) -> ActivationEvidence:
        """Return enrolled evidence only when the live authority paths match."""
        enrolled = AuthorityPaths.for_data_dir(self.data_root)
        if (
            paths.control_root != enrolled.control_root
            or paths.generations_root != enrolled.generations_root
        ):
            raise AuthorityIntegrityError(_ROOT_ERROR)
        return self.evidence


@dataclass(frozen=True)
class TrustedHostRuntime:
    """Verified launch binding for one enrolled root and the current import."""

    data_root: Path
    provider: BoundRootActivationEvidenceProvider
    evidence: ActivationEvidence
    release: VerifiedReleaseArtifacts


def open_trusted_host(enrollment: Path, expected_digest: str) -> TrustedHostRuntime:
    """Load one independently pinned enrollment and bind the current import.

    The operator supplies ``expected_digest`` from a separately retained copy.
    This function never copies ``active.json`` or environment values into the
    enrollment, and it does not invoke a CLI command.
    """
    payload = _parse_enrollment(_read_pinned_enrollment(enrollment, expected_digest))
    data_root = _authorized_data_root(payload["data_root"])
    evidence = _consistent_evidence(payload)
    artifacts = verify_release_artifacts(
        _artifact_paths(payload["artifacts"]),
        TrustedReleaseBinding(payload["release"]["binding_sha256"], evidence),
    )
    _require_wheel_basename(payload["wheel_basename"], evidence, artifacts)
    _bind_imported_package(artifacts)
    provider = BoundRootActivationEvidenceProvider(data_root, evidence)
    _require_active_repository(data_root, provider)
    return TrustedHostRuntime(data_root, provider, evidence, artifacts)


def bind_cli_arguments(runtime: TrustedHostRuntime, argv: Sequence[str]) -> list[str]:
    """Force the enrolled data root and reject a mismatched root-level path."""
    remaining = _strip_root_data_dir(list(argv), runtime.data_root)
    return ["--data-dir", str(runtime.data_root), *remaining]


def trusted_cli_context(
    runtime: TrustedHostRuntime, argv: Sequence[str]
) -> tuple[list[str], dict[str, BoundRootActivationEvidenceProvider]]:
    """Return real Typer arguments and host-injected evidence for one root."""
    return bind_cli_arguments(runtime, argv), {"activation_evidence_provider": runtime.provider}


def run_trusted_cli(
    enrollment: Path, expected_digest: str, argv: Sequence[str] | None = None
) -> None:
    """Verify the pin, then invoke the existing Typer app with bound evidence."""
    runtime = open_trusted_host(enrollment, expected_digest)
    arguments, obj = trusted_cli_context(runtime, list(argv or ()))
    app(args=arguments, obj=obj)


def main(argv: Sequence[str] | None = None) -> None:
    """Operator entrypoint: enrollment path, independently supplied digest, CLI."""
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    try:
        enrollment, digest, command_argv = _parse_host_args(raw)
        run_trusted_cli(enrollment, digest, command_argv)
    except (BackupVerificationError, AuthorityIntegrityError, RepositoryPathError):
        emit_error(
            _ERROR,
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=_HOST_COMMAND,
        )


def _read_pinned_enrollment(path: Path, expected_digest: str) -> bytes:
    if not isinstance(expected_digest, str) or _DIGEST.fullmatch(expected_digest) is None:
        raise BackupVerificationError(_DIGEST_ERROR)
    try:
        raw = read_regular_bytes(path)
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise BackupVerificationError(_DIGEST_ERROR)
    return raw


def _parse_enrollment(raw: bytes) -> dict[str, Any]:
    try:
        payload = _object(raw, _ENROLLMENT_KEYS)
        release = _object(payload["release"], _RELEASE_KEYS)
        artifacts = _object(payload["artifacts"], _ARTIFACT_KEYS)
        wheel = payload["wheel_basename"]
        if type(wheel) is not str or type(payload["data_root"]) is not str:
            raise BackupVerificationError(_ERROR)
        if type(release["binding_sha256"]) is not str:
            raise BackupVerificationError(_ERROR)
        for key in _ARTIFACT_KEYS:
            if type(artifacts[key]) is not str or not artifacts[key]:
                raise BackupVerificationError(_ERROR)
        payload["release"] = release
        payload["artifacts"] = artifacts
        return payload
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _consistent_evidence(payload: dict[str, Any]) -> ActivationEvidence:
    evidence = _evidence(payload["activation_evidence"])
    nested = _evidence(payload["release"]["activation_evidence"])
    if nested != evidence:
        raise BackupVerificationError(_ERROR)
    return evidence


def _authorized_data_root(value: str) -> Path:
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        raise BackupVerificationError(_ERROR)
    root = expanded.absolute()
    try:
        _assert_no_symlink_ancestors(root)
        info = root.lstat()
    except (OSError, RepositoryPathError) as exc:
        raise BackupVerificationError(_ERROR) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise BackupVerificationError(_ERROR)
    return root


def _artifact_paths(artifacts: dict[str, Any]) -> ReleaseArtifactPaths:
    paths = []
    for key in ("wheel", "dependency_lock", "binding"):
        candidate = Path(artifacts[key]).expanduser()
        if not candidate.is_absolute():
            raise BackupVerificationError(_ERROR)
        paths.append(candidate.absolute())
    return ReleaseArtifactPaths(*paths)


def _require_wheel_basename(
    name: str, evidence: ActivationEvidence, artifacts: VerifiedReleaseArtifacts
) -> None:
    expected = f"finjuice-{evidence.installed_release_version}-py3-none-any.whl"
    if name != expected or Path(name).name != name or "/" in name or "\\" in name:
        raise BackupVerificationError(_ERROR)
    if artifacts.release_version != evidence.installed_release_version:
        raise BackupVerificationError(_ERROR)
    if artifacts.release_artifact_sha256 != evidence.installed_release_artifact_sha256:
        raise BackupVerificationError(_ERROR)


def _bind_imported_package(artifacts: VerifiedReleaseArtifacts) -> None:
    if _imported_package_inventory() != _wheel_package_inventory(artifacts.wheel_bytes):
        raise BackupVerificationError(_CODE_ERROR)


def _imported_package_inventory() -> dict[str, str]:
    import finjuice

    init_path = Path(finjuice.__file__).expanduser().absolute()
    try:
        _assert_no_symlink_ancestors(init_path)
    except (OSError, RepositoryPathError) as exc:
        raise BackupVerificationError(_CODE_ERROR) from exc
    if init_path.name != "__init__.py":
        raise BackupVerificationError(_CODE_ERROR)
    return _directory_inventory(init_path.parent)


def _directory_inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            if current_path != root:
                _assert_no_symlink_ancestors(current_path)
        except (OSError, RepositoryPathError) as exc:
            raise BackupVerificationError(_CODE_ERROR) from exc
        dirnames[:] = sorted(name for name in dirnames if name != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            inventory[relative] = _file_digest(path)
    if not inventory:
        raise BackupVerificationError(_CODE_ERROR)
    return inventory


def _file_digest(path: Path) -> str:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise BackupVerificationError(_CODE_ERROR)
        return hashlib.sha256(read_regular_bytes(path)).hexdigest()
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_CODE_ERROR) from None


def _wheel_package_inventory(wheel_bytes: bytes) -> dict[str, str]:
    inventory: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
            for name in archive.namelist():
                relative = _package_member(name)
                if relative is None:
                    continue
                if relative in inventory:
                    raise BackupVerificationError(_CODE_ERROR)
                inventory[relative] = hashlib.sha256(archive.read(name)).hexdigest()
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_CODE_ERROR) from None
    if not inventory:
        raise BackupVerificationError(_CODE_ERROR)
    return inventory


def _package_member(name: str) -> str | None:
    if name.endswith("/") or not name.startswith("finjuice/") or ".dist-info/" in name:
        return None
    relative = name.removeprefix("finjuice/")
    parts = relative.split("/")
    if not relative or "__pycache__" in parts or relative.endswith(".pyc"):
        return None
    return relative


def _require_active_repository(
    data_root: Path, provider: BoundRootActivationEvidenceProvider
) -> None:
    try:
        dispatch = resolve_storage_authority(data_root, provider)
    except (AuthorityIntegrityError, RepositoryPathError):
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    if not isinstance(dispatch.authority, RepositoryAuthority):
        raise BackupVerificationError(_ERROR)


def _parse_host_args(argv: list[str]) -> tuple[Path, str, list[str]]:
    options: dict[str, str] = {}
    allowed = {"--enrollment", "--digest"}
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            index += 1
            break
        flag, separator, value = argument.partition("=")
        if flag not in allowed:
            break
        if flag in options:
            raise BackupVerificationError(_ERROR)
        index += 1
        if not separator:
            if index == len(argv):
                raise BackupVerificationError(_ERROR)
            value = argv[index]
            index += 1
        options[flag] = value
    if set(options) != allowed or not all(options.values()):
        raise BackupVerificationError(_ERROR)
    return Path(options["--enrollment"]), options["--digest"], argv[index:]


def _strip_root_data_dir(argv: list[str], enrolled: Path) -> list[str]:
    remaining: list[str] = []
    index = 0
    command_seen = False
    while index < len(argv):
        argument = argv[index]
        if not command_seen and argument in {"--data-dir", "-d"}:
            if index + 1 >= len(argv):
                raise BackupVerificationError(_ROOT_ERROR)
            _require_same_root(Path(argv[index + 1]), enrolled)
            index += 2
            continue
        if not command_seen and argument.startswith("--data-dir="):
            _require_same_root(Path(argument.split("=", 1)[1]), enrolled)
            index += 1
            continue
        compact = re.fullmatch(r"-([vh]*)d(.+)", argument) if not command_seen else None
        if compact is not None:
            _require_same_root(Path(compact[2]), enrolled)
            remaining.extend("-" + flag for flag in compact[1])
            index += 1
            continue
        grouped = re.fullmatch(r"-([vh]+)d", argument) if not command_seen else None
        if grouped is not None:
            if index + 1 >= len(argv):
                raise BackupVerificationError(_ROOT_ERROR)
            _require_same_root(Path(argv[index + 1]), enrolled)
            remaining.extend("-" + flag for flag in grouped[1])
            index += 2
            continue
        if not command_seen and (not argument.startswith("-") or argument == "--"):
            command_seen = True
        elif not command_seen and argument not in _ROOT_FLAGS and argument.startswith("--"):
            command_seen = True
        remaining.append(argument)
        index += 1
    return remaining


def _require_same_root(candidate: Path, enrolled: Path) -> None:
    expanded = candidate.expanduser().absolute()
    try:
        _assert_no_symlink_ancestors(expanded)
    except (OSError, RepositoryPathError) as exc:
        raise BackupVerificationError(_ROOT_ERROR) from exc
    if expanded != enrolled:
        raise BackupVerificationError(_ROOT_ERROR)


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
    try:
        return ActivationEvidence(
            payload["installed_release_version"],
            payload["installed_release_artifact_sha256"],
            payload["verified_migration_manifest_sha256"],
            payload["verified_pre_cutover_backup_manifest_sha256"],
        )
    except ValueError as exc:
        raise BackupVerificationError(_ERROR) from exc


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise BackupVerificationError(_ERROR)
        document[key] = value
    return document


if __name__ == "__main__":
    main()
