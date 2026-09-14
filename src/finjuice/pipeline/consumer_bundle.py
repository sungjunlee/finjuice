"""Immutable legacy analysis inputs bound to one captured SQLite revision.

The bundle is a derived projection. It copies primary capture bytes for the
historical Banksalad balance/investments/loans partitions and an optional
external overlay. Live CSV, caller-supplied pins, native reports, ownership,
and currency conversion are never inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.backup.types import DATA_ROOT_NAME
from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.sqlite.errors import ObjectCorruptionError, RepositoryPathError
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore, _assert_no_symlink_ancestors
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioReadSnapshot
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

MATERIALIZATION_POLICY = "legacy_analysis_consumer_bundle.v1"
BUNDLE_FORMAT = "finjuice.legacy-analysis-consumer-bundle.v1"
MANIFEST_NAME = "manifest.json"
OVERLAY_OUTPUT = "overlay"
OVERLAY_ROOTS = frozenset({"overlay", "external-overlay"})
_PARTITION = re.compile(
    r"banksalad/(balance|investments|loans)/[0-9]{4}/(0[1-9]|1[0-2])/"
    r"(balance|investments|loans)\.csv"
)
_LIMITATIONS = (
    "historical_legacy_reference_projection",
    "legacy_reference_reports_are_unverified",
    "no_native_report_coverage",
    "no_operational_acceptance",
    "no_owner_inference",
    "no_currency_conversion",
    "primary_capture_bytes_only",
)
_STAGING_PREFIX = ".finjuice-consumer-bundle."


class ConsumerBundleError(ValueError):
    """Static failure for an unpublished or unusable legacy consumer bundle."""


@dataclass(frozen=True)
class LegacyConsumerBundle:
    """One complete published directory of revision-pinned consumer inputs."""

    directory: Path
    manifest_path: Path
    overlay_path: Path | None
    files: tuple[str, ...]
    manifest: dict[str, Any]


def materialize_legacy_consumer_bundle(
    reader: RepositoryReader,
    output_root: Path,
    *,
    data_dir: Path | None = None,
    source_roots: tuple[Path, ...] = (),
) -> LegacyConsumerBundle:
    """Publish legacy analysis CSVs and optional overlay from one reader snapshot.

    Identity comes from the opened repository revision. Callers choose only the
    output directory. Existing complete matching bundles are left in place.
    """
    snapshot = reader.portfolio_snapshot()
    files, identities = _bundle_payload(reader, snapshot)
    output = _validated_output(output_root, reader.paths, data_dir, source_roots)
    manifest = _manifest(snapshot, identities, files)
    if output.exists():
        return _reuse_complete(output, snapshot, files, manifest)
    _publish(output, files, manifest)
    return _bundle(output, files, manifest)


def _bundle_payload(
    reader: RepositoryReader, snapshot: PortfolioReadSnapshot
) -> tuple[dict[str, bytes], dict[str, Any]]:
    scopes = reader.capture_file_scopes()
    artifacts = {row["source_artifact_id"]: row for row in reader.rows("source_artifacts")}
    occurrences = {row["entity_id"]: row for row in reader.rows("source_occurrences")}
    partitions = _partition_files(snapshot, scopes, occurrences, artifacts, reader.paths)
    overlay = _overlay_file(scopes, occurrences, artifacts, reader.paths)
    files = dict(partitions)
    if overlay is not None:
        files[OVERLAY_OUTPUT] = overlay[0]
    return files, {
        "partitions": _partition_identities(partitions, scopes, occurrences),
        "overlay": overlay,
    }


def _partition_files(
    snapshot: PortfolioReadSnapshot,
    scopes: tuple[dict[str, Any], ...],
    occurrences: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    paths: GenerationPaths,
) -> dict[str, bytes]:
    selected: dict[str, dict[str, Any]] = {}
    for scope in scopes:
        path = _partition_path(scope)
        if path is None:
            continue
        if path in selected:
            raise ConsumerBundleError("Primary capture partition identity is ambiguous.")
        selected[path] = scope
    scoped = {row["source_occurrence_id"] for row in snapshot.source_scopes}
    files: dict[str, bytes] = {}
    for path, scope in selected.items():
        occurrence_id = scope["source_occurrence_id"]
        if occurrence_id not in scoped:
            raise ConsumerBundleError("Primary capture partition is missing portfolio evidence.")
        files[path] = _artifact_bytes(paths, occurrences, artifacts, occurrence_id)
    return files


def _partition_path(scope: dict[str, Any]) -> str | None:
    path = scope.get("path")
    if scope.get("root") != DATA_ROOT_NAME or not isinstance(path, str):
        return None
    match = _PARTITION.fullmatch(path)
    if match is None or match[1] != match[3]:
        return None
    return path


def _overlay_file(
    scopes: tuple[dict[str, Any], ...],
    occurrences: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    paths: GenerationPaths,
) -> tuple[bytes, dict[str, Any]] | None:
    overlays = [scope for scope in scopes if scope.get("root") in OVERLAY_ROOTS]
    if len(overlays) > 1:
        raise ConsumerBundleError("Overlay capture identity is ambiguous.")
    if not overlays:
        return None
    scope = overlays[0]
    content = _artifact_bytes(paths, occurrences, artifacts, scope["source_occurrence_id"])
    return content, {
        "presence": "present",
        "output": OVERLAY_OUTPUT,
        "root": scope["root"],
        "path": scope["path"],
        "source_occurrence_id": scope["source_occurrence_id"],
        "capture_manifest_digest": scope["capture_manifest_digest"],
        "source_artifact_id": occurrences[scope["source_occurrence_id"]]["source_artifact_id"],
    }


def _partition_identities(
    partitions: dict[str, bytes],
    scopes: tuple[dict[str, Any], ...],
    occurrences: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_path = {scope["path"]: scope for scope in scopes if _partition_path(scope) is not None}
    identities = []
    for path in sorted(partitions):
        scope = by_path[path]
        occurrence = occurrences[scope["source_occurrence_id"]]
        identities.append(
            {
                "path": path,
                "root": DATA_ROOT_NAME,
                "source_occurrence_id": scope["source_occurrence_id"],
                "capture_manifest_digest": scope["capture_manifest_digest"],
                "source_artifact_id": occurrence["source_artifact_id"],
            }
        )
    return identities


def _artifact_bytes(
    paths: GenerationPaths,
    occurrences: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    occurrence_id: str,
) -> bytes:
    occurrence = occurrences.get(occurrence_id)
    if occurrence is None or occurrence.get("occurrence_kind") != "legacy_capture":
        raise ConsumerBundleError("Primary capture occurrence is missing.")
    artifact_id = occurrence["source_artifact_id"]
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise ConsumerBundleError("Primary capture artifact is missing.")
    try:
        verified = SourceObjectStore(paths).verify(artifact_id, artifact["byte_length"])
        content = (paths.root / verified.relative_path).read_bytes()
    except (ObjectCorruptionError, RepositoryPathError, OSError) as exc:
        raise ConsumerBundleError("Primary capture bytes could not be verified.") from exc
    if len(content) != artifact["byte_length"] or _digest(content) != artifact_id:
        raise ConsumerBundleError("Primary capture bytes do not match their identity.")
    return content


def _manifest(
    snapshot: PortfolioReadSnapshot,
    identities: dict[str, Any],
    files: dict[str, bytes],
) -> dict[str, Any]:
    overlay = identities["overlay"]
    overlay_identity: dict[str, Any]
    if overlay is None:
        overlay_identity = {"presence": "absent"}
    else:
        overlay_identity = {
            **overlay[1],
            "sha256": _digest(overlay[0]),
            "byte_count": len(overlay[0]),
        }
    outputs = {
        path: {"sha256": _digest(content), "byte_count": len(content)}
        for path, content in files.items()
    }
    partition_identities = [{**item, **outputs[item["path"]]} for item in identities["partitions"]]
    return {
        "format": BUNDLE_FORMAT,
        "materialization_policy": MATERIALIZATION_POLICY,
        "authority": "repository",
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "sqlite_schema_version": snapshot.info.schema_version,
        "legacy_reports_support": snapshot.legacy_reports_support,
        "limitations": list(_LIMITATIONS),
        "source_identities": {
            "partitions": partition_identities,
            "overlay": overlay_identity,
        },
        "outputs": outputs,
    }


def _validated_output(
    output_root: Path,
    repository: GenerationPaths,
    data_dir: Path | None,
    source_roots: tuple[Path, ...],
) -> Path:
    try:
        output = _absolute(output_root, allow_missing=True)
        protected = [_absolute(repository.root, allow_missing=True)]
        if data_dir is not None:
            data = _absolute(data_dir, allow_missing=True)
            protected.append(data)
            control = AuthorityPaths.for_data_dir(data_dir)
            protected.extend(
                (
                    _absolute(control.control_root, allow_missing=True),
                    _absolute(control.generations_root, allow_missing=True),
                )
            )
        protected.extend(_absolute(path, allow_missing=True) for path in source_roots)
        for root in protected:
            _reject_overlap(output, root)
        if output.exists():
            _assert_no_symlink_ancestors(output)
            info = output.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ConsumerBundleError("Output root is unsafe or not a directory.")
        return output
    except (ConsumerBundleError, RepositoryPathError, OSError) as exc:
        if isinstance(exc, ConsumerBundleError):
            raise
        raise ConsumerBundleError("Output overlaps a protected root or is unsafe.") from exc


def _reuse_complete(
    output: Path,
    snapshot: PortfolioReadSnapshot,
    files: dict[str, bytes],
    manifest: dict[str, Any],
) -> LegacyConsumerBundle:
    published = _read_manifest(output / MANIFEST_NAME)
    if published != manifest:
        raise ConsumerBundleError("Previous output does not match this snapshot bundle.")
    for path, content in files.items():
        actual = output / path
        if not actual.is_file() or actual.is_symlink() or actual.read_bytes() != content:
            raise ConsumerBundleError("Previous output does not match this snapshot bundle.")
    extras = {item.relative_to(output).as_posix() for item in output.rglob("*") if item.is_file()}
    if extras != set(files) | {MANIFEST_NAME}:
        raise ConsumerBundleError("Previous output does not match this snapshot bundle.")
    if (
        published["dataset_generation"] != snapshot.info.dataset_generation
        or published["dataset_revision"] != snapshot.info.dataset_revision
    ):
        raise ConsumerBundleError("Previous output does not match this snapshot bundle.")
    return _bundle(output, files, published)


def _publish(output: Path, files: dict[str, bytes], manifest: dict[str, Any]) -> None:
    parent = output.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink_ancestors(parent)
        staging = parent / f"{_STAGING_PREFIX}{uuid.uuid4().hex}.tmp"
        staging.mkdir(mode=0o700)
    except (RepositoryPathError, OSError) as exc:
        raise ConsumerBundleError("Consumer bundle staging could not be created.") from exc
    published = False
    try:
        for relative, content in files.items():
            _write_file(staging, relative, content)
        _write_file(staging, MANIFEST_NAME, _canonical(manifest))
        _reject_staging_symlinks(staging)
        rename_exclusive(staging, output)
        published = True
        _fsync_directory(parent)
    except OSError:
        if not published:
            _discard(staging)
        raise ConsumerBundleError("Consumer bundle could not be published completely.") from None
    except ConsumerBundleError:
        if not published:
            _discard(staging)
        raise


def _bundle(
    output: Path, files: dict[str, bytes], manifest: dict[str, Any]
) -> LegacyConsumerBundle:
    overlay = output / OVERLAY_OUTPUT if OVERLAY_OUTPUT in files else None
    return LegacyConsumerBundle(
        directory=output,
        manifest_path=output / MANIFEST_NAME,
        overlay_path=overlay,
        files=tuple(sorted(files)),
        manifest=manifest,
    )


def _write_file(root: Path, relative: str, content: bytes) -> None:
    path = Path(relative)
    if path.is_absolute() or path.as_posix() != relative or ".." in path.parts:
        raise ConsumerBundleError("Bundle output path is unsafe.")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except OSError as exc:
        raise ConsumerBundleError("Bundle file could not be created.") from exc
    try:
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Bundle write made no progress.")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _absolute(path: Path, *, allow_missing: bool = False) -> Path:
    absolute = path.expanduser().absolute()
    _assert_no_symlink_ancestors(absolute, allow_missing=allow_missing)
    return Path(os.path.abspath(absolute))


def _reject_overlap(left: Path, right: Path) -> None:
    if left == right or left.is_relative_to(right) or right.is_relative_to(left):
        raise ConsumerBundleError("Output overlaps a protected data, repository, or source root.")


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConsumerBundleError("Previous output is not a complete consumer bundle.") from exc
    if not isinstance(payload, dict):
        raise ConsumerBundleError("Previous output is not a complete consumer bundle.")
    return payload


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _reject_staging_symlinks(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in dirnames + filenames:
            if (current / name).is_symlink():
                raise ConsumerBundleError("Bundle staging contains a symlink.")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _discard(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        return


__all__ = [
    "BUNDLE_FORMAT",
    "ConsumerBundleError",
    "LegacyConsumerBundle",
    "MANIFEST_NAME",
    "MATERIALIZATION_POLICY",
    "OVERLAY_OUTPUT",
    "materialize_legacy_consumer_bundle",
]
