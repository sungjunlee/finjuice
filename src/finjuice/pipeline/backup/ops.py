"""Create, verify, and restore operations for legacy full backups."""

from __future__ import annotations

import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finjuice import get_version
from finjuice.pipeline.backup.errors import BackupError, invalid
from finjuice.pipeline.backup.io import (
    atomic_publish,
    cleanup_tree,
    copy_inventory,
    copy_payload_entry,
    finalize_directory_metadata,
    fsync_parent_chain,
    mkdir_private,
    new_staging_dir,
    payload_root_dir,
    preflight_space,
    restore_payload_destination,
    run_with_staging,
    write_text_atomic,
)
from finjuice.pipeline.backup.manifest import (
    backup_dir_from_manifest_path,
    build_manifest,
    compute_manifest_digest,
    consistency_payload,
    digest_text,
    inventory_definition_digest,
    load_manifest,
    payload_relative,
    read_captured_data_schema,
    validate_attempt_id,
    validate_manifest_structure,
)
from finjuice.pipeline.backup.paths import (
    classify_mode,
    lstat_or_raise,
    reject_overlap,
    reject_symlink_chain,
    require_outside_program_repo,
    validate_root_name,
)
from finjuice.pipeline.backup.publish import require_mutation_platform
from finjuice.pipeline.backup.scan import fingerprint_file, fingerprints_equal, scan_roots
from finjuice.pipeline.backup.types import (
    COMPLETION_MARKER,
    DATA_ROOT_NAME,
    INACTIVE_GENERATION,
    MANIFEST_FILENAME,
    PAYLOAD_DIRNAME,
    ROOTS_DIRNAME,
    SCHEMA_VERSION,
    BackupResult,
    ConsistencyEvidence,
    CreateRequest,
    Inventory,
    SourceRoot,
)


def require_consistency(evidence: ConsistencyEvidence) -> ConsistencyEvidence:
    """Require operator-confirmed stopped writers or a named snapshot."""
    if (
        evidence.kind == "stopped_writers"
        and evidence.stopped_writers
        and evidence.snapshot_name is None
    ):
        return evidence
    if (
        evidence.kind == "named_snapshot"
        and evidence.snapshot_name
        and not evidence.stopped_writers
    ):
        return evidence
    raise BackupError(
        "Capture requires stopped-writer evidence or a named quiesced snapshot.",
        code="INVALID_ARGS",
        suggestion="Pass --consistency and the matching evidence option.",
    )


def _data_root(source: Path) -> SourceRoot:
    return SourceRoot(
        name=DATA_ROOT_NAME,
        presence="required",
        path=source,
        role="legacy_data_tree",
    )


def bind_roots(request: CreateRequest) -> list[SourceRoot]:
    """Validate source/output/root paths and return the closed root list."""
    source = require_outside_program_repo(request.source, context="backup source")
    if classify_mode(lstat_or_raise(source).st_mode) != "directory":
        raise BackupError("Backup data source must be a directory.", code="INVALID_ARGS")
    output = require_outside_program_repo(request.output, context="backup output")
    reject_overlap(source, output)
    roots = [_data_root(source)]
    seen: dict[str, Path | None] = {DATA_ROOT_NAME: source}
    for spec in request.extra_roots:
        _bind_extra_root(spec, source, output, roots, seen)
    return roots


def _bind_extra_root(
    spec: SourceRoot,
    source: Path,
    output: Path,
    roots: list[SourceRoot],
    seen: dict[str, Path | None],
) -> None:
    name = validate_root_name(spec.name)
    if name in seen:
        raise BackupError("Duplicate source-root name.", code="INVALID_ARGS")
    path = None
    if spec.path is not None:
        path = require_outside_program_repo(spec.path, context="backup source root")
        reject_overlap(path, source)
        reject_overlap(path, output)
        for existing in seen.values():
            if existing is not None:
                reject_overlap(path, existing)
    elif spec.presence != "optional":
        raise BackupError("A required external root is missing.", code="FILE_NOT_FOUND")
    seen[name] = path
    roots.append(SourceRoot(name=name, presence=spec.presence, path=path, role=spec.role))


def _result_from_manifest(
    manifest: dict[str, Any],
    *,
    status: str,
    generation_status: str | None = None,
) -> BackupResult:
    return BackupResult(
        status=status,  # type: ignore[arg-type]
        schema_version=str(manifest.get("schema_version", SCHEMA_VERSION)),
        manifest_digest=str(manifest.get("canonical_digest", "")),
        entry_count=int(manifest.get("entry_count", 0)),
        file_count=int(manifest.get("file_count", 0)),
        directory_count=int(manifest.get("directory_count", 0)),
        byte_count=int(manifest.get("byte_count", 0)),
        root_count=len(manifest.get("roots", [])),
        absent_optional_count=sum(
            1 for root in manifest.get("roots", []) if root.get("state") == "intentionally_absent"
        ),
        finjuice_version=str(manifest.get("finjuice_version", get_version())),
        data_schema_version=manifest.get("data_schema_version"),
        data_schema_version_status=manifest.get("data_schema_version_status", "invalid"),
        consistency_kind=str(manifest.get("consistency", {}).get("kind", "")),
        generation_status=generation_status,
    )


def _write_manifest_and_marker(staging: Path, manifest: dict[str, Any]) -> None:
    write_text_atomic(
        staging / MANIFEST_FILENAME,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    write_text_atomic(staging / COMPLETION_MARKER, f"{manifest['canonical_digest']}\n")


def create_backup(request: CreateRequest) -> BackupResult:
    """Create a complete legacy backup or return already_complete."""
    require_mutation_platform()
    evidence = require_consistency(request.consistency)
    validate_attempt_id(request.parent_attempt_id)
    roots = bind_roots(request)
    output = require_outside_program_repo(request.output, context="backup output")
    if os.path.lexists(output):
        reject_symlink_chain(output)
        return _existing_output(output, roots, evidence, request.parent_attempt_id)
    capture = {
        "attempt_id": uuid.uuid4().hex,
        "parent_attempt_id": request.parent_attempt_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    pre = scan_roots(roots)
    parent = _prepare_output_parent(output)
    preflight_space(parent, pre.byte_count)
    run_with_staging(
        parent,
        lambda staging: _capture_to_staging(staging, roots, pre, evidence, capture),
        output,
    )
    _backup_dir, manifest = _load_verified_backup(output)
    return _result_from_manifest(manifest, status="ok")


def _prepare_output_parent(output: Path) -> Path:
    parent = output.parent
    reject_symlink_chain(parent)
    parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_chain(parent)
    return parent


def _capture_to_staging(
    staging: Path,
    roots: list[SourceRoot],
    pre: Inventory,
    evidence: ConsistencyEvidence,
    capture: dict[str, Any],
) -> None:
    copy_inventory(roots, pre.entries, staging)
    post = scan_roots(_staged_as_source(roots, staging))
    if not fingerprints_equal(_remap_scan(pre), _remap_scan(post)):
        raise invalid("Source changed during capture.")
    live = scan_roots(roots)
    if not fingerprints_equal(pre, live):
        raise invalid("Source changed during capture.")
    captured_data = payload_root_dir(staging, roots[0])
    data_schema_version, data_schema_status = read_captured_data_schema(captured_data)
    manifest = build_manifest(
        inventory=pre,
        evidence=evidence,
        data_schema_version=data_schema_version,
        data_schema_version_status=data_schema_status,
        capture={**capture, "completed_at": datetime.now(timezone.utc).isoformat()},
    )
    _write_manifest_and_marker(staging, manifest)


def _staged_as_source(roots: list[SourceRoot], staging: Path) -> list[SourceRoot]:
    remapped: list[SourceRoot] = []
    for spec in roots:
        if spec.path is None:
            remapped.append(spec)
            continue
        remapped.append(
            SourceRoot(
                name=spec.name,
                presence=spec.presence,
                path=payload_root_dir(staging, spec),
                role=spec.role,
            )
        )
    return remapped


def _remap_scan(scanned: Inventory) -> Inventory:
    """Drop inode identity so staged copies can be compared by digest."""
    stripped = Inventory(roots=scanned.roots, entries=[])
    for entry in scanned.entries:
        stripped.entries.append(
            entry.__class__(
                root=entry.root,
                path=entry.path,
                entry_type=entry.entry_type,
                size=entry.size,
                mode=entry.mode,
                mtime_ns=entry.mtime_ns,
                sha256=entry.sha256,
                identity=None,
            )
        )
    return stripped


def _existing_output(
    output: Path,
    roots: list[SourceRoot],
    evidence: ConsistencyEvidence,
    parent_attempt_id: str | None,
) -> BackupResult:
    manifest_path = output / MANIFEST_FILENAME if output.is_dir() else output
    backup_dir, manifest = _load_verified_backup(manifest_path)
    current = scan_roots(roots)
    if manifest.get("inventory_definition_digest") != inventory_definition_digest(roots):
        raise invalid("Output already exists and does not match this input.")
    if not _manifest_matches_inventory(manifest, current):
        raise invalid("Output already exists and does not match this input.")
    if manifest.get("consistency") != consistency_payload(evidence):
        raise invalid("Output already exists and does not match this input.")
    if manifest["capture"]["parent_attempt_id"] != parent_attempt_id:
        raise invalid("Output already exists and does not match this capture lineage.")
    # A previous attempt may have published the directory before its parent
    # fsync failed. Re-establish durability before reporting a successful retry.
    fsync_parent_chain(backup_dir.parent)
    return _result_from_manifest(manifest, status="already_complete")


def _manifest_matches_inventory(manifest: dict[str, Any], inventory: Inventory) -> bool:
    expected = {(item.root, item.path): item for item in inventory.entries}
    actual = manifest.get("entries", [])
    if len(actual) != len(expected):
        return False
    for item in actual:
        entry = expected.get((item.get("root"), item.get("path")))
        if entry is None:
            return False
        digest = item.get("sha256")
        expected_digest = None if entry.sha256 is None else digest_text(entry.sha256)
        if (
            item.get("type"),
            item.get("size"),
            item.get("mode"),
            item.get("mtime_ns"),
            digest,
        ) != (
            entry.entry_type,
            entry.size,
            entry.mode,
            entry.mtime_ns,
            expected_digest,
        ):
            return False
    return True


def verify_backup(manifest_path: Path) -> BackupResult:
    """Verify a published backup without modifying it."""
    _backup_dir, manifest = _load_verified_backup(manifest_path)
    return _result_from_manifest(manifest, status="ok")


def _load_verified_backup(manifest_path: Path) -> tuple[Path, dict[str, Any]]:
    """Load and verify one immutable manifest object for a command operation."""
    location = reject_symlink_chain(manifest_path)
    backup_dir = backup_dir_from_manifest_path(location)
    reject_symlink_chain(backup_dir)
    manifest_file = backup_dir / MANIFEST_FILENAME
    marker = backup_dir / COMPLETION_MARKER
    reject_symlink_chain(manifest_file)
    reject_symlink_chain(marker)
    if not marker.is_file() or marker.is_symlink():
        raise BackupError("Backup completion marker is missing.", code="VALIDATION_FAILED")
    manifest = load_manifest(manifest_file)
    validate_manifest_structure(manifest)
    expected = compute_manifest_digest(manifest)
    if manifest.get("canonical_digest") != expected:
        raise BackupError("Backup manifest digest does not match.", code="VALIDATION_FAILED")
    marker_text = marker.read_text(encoding="utf-8").strip()
    if marker_text != expected:
        raise BackupError("Backup completion marker does not match.", code="VALIDATION_FAILED")
    _verify_payload(backup_dir, manifest)
    _verify_data_schema_evidence(backup_dir, manifest)
    return backup_dir, manifest


def _verify_data_schema_evidence(backup_dir: Path, manifest: dict[str, Any]) -> None:
    version, status = read_captured_data_schema(backup_dir / PAYLOAD_DIRNAME / DATA_ROOT_NAME)
    if (
        manifest.get("data_schema_version") != version
        or manifest.get("data_schema_version_status") != status
    ):
        raise invalid("Backup data schema evidence does not match the captured payload.")


def _verify_payload(backup_dir: Path, manifest: dict[str, Any]) -> None:
    expected_paths: set[Path] = set()
    for entry in manifest["entries"]:
        rel = payload_relative(str(entry["root"]), str(entry["path"]))
        expected_paths.add(rel)
        source = backup_dir / rel
        reject_symlink_chain(source)
        source_stat = lstat_or_raise(source)
        kind = classify_mode(source_stat.st_mode)
        if kind != entry["type"]:
            raise invalid("Backup payload does not match the manifest.")
        if kind != "directory":
            identity, digest = fingerprint_file(source)
            expected_digest = str(entry.get("sha256") or "").removeprefix("sha256:")
            if identity.size != int(entry["size"]) or digest != expected_digest:
                raise invalid("Backup payload hash or size does not match.")
        source_mtime = getattr(
            source_stat,
            "st_mtime_ns",
            int(source_stat.st_mtime * 1_000_000_000),
        )
        if (
            stat.S_IMODE(source_stat.st_mode) != int(entry["mode"], 8)
            or source_mtime != entry["mtime_ns"]
        ):
            raise invalid("Backup payload metadata does not match the manifest.")
    _reject_extra_payload(backup_dir, expected_paths)


def _reject_extra_payload(backup_dir: Path, expected: set[Path]) -> None:
    payload = backup_dir / PAYLOAD_DIRNAME
    reject_symlink_chain(payload)
    if not payload.exists():
        if expected:
            raise BackupError("Backup payload is missing.", code="VALIDATION_FAILED")
        return
    actual: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(payload, followlinks=False):
        rel_dir = Path(dirpath).relative_to(backup_dir)
        actual.add(rel_dir)
        for name in dirnames + filenames:
            child = Path(dirpath) / name
            if os.path.islink(child):
                raise BackupError("Backup payload contains a symlink.", code="VALIDATION_FAILED")
            actual.add(child.relative_to(backup_dir))
    containers = {Path(PAYLOAD_DIRNAME), Path(PAYLOAD_DIRNAME) / ROOTS_DIRNAME}
    extra = actual - expected - containers
    missing = expected - actual
    if extra or missing:
        raise invalid("Backup payload entries conflict with the manifest.")


def restore_backup(
    manifest_path: Path,
    target: Path,
    *,
    active_data_dir: Path,
) -> BackupResult:
    """Restore a verified backup into an isolated inactive target."""
    require_mutation_platform()
    if active_data_dir is None:
        raise invalid("Active data directory is required for isolated restore.")
    backup_dir, manifest = _load_verified_backup(manifest_path)
    destination = require_outside_program_repo(target, context="backup restore target")
    existing_target = _reject_restore_target(destination, backup_dir, active_data_dir)
    parent = destination.parent
    reject_symlink_chain(parent)
    parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_chain(parent)
    preflight_space(parent, int(manifest.get("byte_count", 0)))
    _publish_restore(parent, destination, backup_dir, manifest, existing_target)
    return _result_from_manifest(manifest, status="ok", generation_status="inactive")


def _reject_restore_target(
    destination: Path,
    backup_dir: Path,
    active_data_dir: Path,
) -> os.stat_result | None:
    reject_overlap(destination, backup_dir, code="VALIDATION_FAILED")
    active = reject_symlink_chain(active_data_dir)
    reject_overlap(destination, active, code="VALIDATION_FAILED")
    if not destination.exists():
        return None
    if destination.is_symlink() or not destination.is_dir():
        raise invalid("Restore target must be a new or empty directory.")
    if any(destination.iterdir()):
        raise BackupError("Restore target is not empty.", code="VALIDATION_FAILED")
    return destination.lstat()


def _publish_restore(
    parent: Path,
    destination: Path,
    backup_dir: Path,
    manifest: dict[str, Any],
    existing_target: os.stat_result | None,
) -> None:
    staging = new_staging_dir(parent)
    mkdir_private(staging)
    try:
        _fill_restore_staging(staging, backup_dir, manifest)
        if existing_target is not None:
            _check_existing_restore_target(destination, existing_target)
        atomic_publish(staging, destination, replace_empty=existing_target is not None)
    except Exception:
        cleanup_tree(staging)
        raise


def _check_existing_restore_target(destination: Path, expected: os.stat_result) -> None:
    current = destination.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(current, name) != getattr(expected, name) for name in fields):
        raise invalid("Restore target changed while the backup was being restored.")
    if any(destination.iterdir()):
        raise invalid("Restore target changed while the backup was being restored.")


def _fill_restore_staging(staging: Path, backup_dir: Path, manifest: dict[str, Any]) -> None:
    directory_metadata: list[tuple[Path, int, int]] = []
    for entry in manifest["entries"]:
        dest = restore_payload_destination(staging, str(entry["root"]))
        destination = dest if entry["path"] == "." else dest / str(entry["path"])
        copy_payload_entry(backup_dir, destination, entry)
        if entry["type"] == "directory":
            directory_metadata.append(
                (destination, int(str(entry["mode"]), 8), int(entry["mtime_ns"]))
            )
    finalize_directory_metadata(directory_metadata)
    write_text_atomic(
        staging / INACTIVE_GENERATION,
        json.dumps(
            {
                "status": "inactive",
                "kind": "restored_legacy_backup",
                "manifest_digest": manifest["canonical_digest"],
            },
            sort_keys=True,
        )
        + "\n",
    )
