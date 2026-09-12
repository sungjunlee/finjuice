"""Build inactive preservation generations behind one directory publication boundary."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup import verify_backup
from finjuice.pipeline.backup.io import atomic_publish, fsync_parent_chain, write_text_atomic
from finjuice.pipeline.backup.manifest import payload_relative, validate_attempt_id
from finjuice.pipeline.backup.paths import (
    reject_overlap,
    reject_symlink_chain,
    require_outside_program_repo,
)
from finjuice.pipeline.backup.publish import require_mutation_platform
from finjuice.pipeline.backup.types import MANIFEST_FILENAME
from finjuice.pipeline.migration.adapters import preserve_file
from finjuice.pipeline.migration.common import (
    MANIFEST,
    MARKER,
    MIGRATION_VERSION,
    PLAN_VERSION,
    MigrationError,
    MigrationResult,
    canonical,
    file_digest,
    load_sealed,
    seal,
    tree_inventory,
)
from finjuice.pipeline.migration.plan import file_context
from finjuice.pipeline.storage.sqlite import (
    ConfigRevisionRecord,
    GenerationPaths,
    MigrationIdentityRecord,
    RepositoryBuilder,
    SourceOccurrenceRecord,
    migration_entity_id,
)


def baseline_origin(capture: dict[str, Any]) -> dict[str, Any]:
    checksum = capture["canonical_digest"]
    return {
        "origin_kind": "legacy_current_state",
        "dataset_revision": 0,
        "capture_manifest_digest": checksum,
        "revision_id": migration_entity_id(checksum, "config_revision", {"baseline": True}),
    }


def populate_repository(root: Path, capture: dict[str, Any], paths: GenerationPaths) -> None:
    """Populate only preserved source state; create no historical audit or approval."""
    checksum = capture["canonical_digest"]
    generation = migration_entity_id(checksum, "dataset_generation", {"baseline": True})
    with RepositoryBuilder(paths, generation) as builder:
        artifact = builder.publish_source_path(root / MANIFEST_FILENAME)
        occurrence = migration_entity_id(checksum, "source_occurrence", {"capture_manifest": True})
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence,
                artifact.artifact_id,
                "legacy_capture_manifest",
                parser_version=MIGRATION_VERSION,
            )
        )
        builder.add_migration_identity(
            MigrationIdentityRecord(
                occurrence,
                checksum,
                "source_occurrence",
                {"capture_manifest": True},
            )
        )
        origin = baseline_origin(capture)
        builder.add_config_revision(
            ConfigRevisionRecord(
                origin["revision_id"],
                "other",
                artifact.artifact_id,
                occurrence,
                "parsed",
                MIGRATION_VERSION,
                origin,
            )
        )
        builder.add_migration_identity(
            MigrationIdentityRecord(
                origin["revision_id"],
                checksum,
                "config_revision",
                {"baseline": True},
            )
        )
        for entry in capture["entries"]:
            if entry["type"] == "file":
                source = root / payload_relative(entry["root"], entry["path"])
                preserve_file(builder, source, file_context(capture, entry))
        builder.finalize()


def validate_source(root: Path, plan: dict[str, Any]) -> None:
    verify_backup(root / MANIFEST_FILENAME)
    capture = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if capture != plan["capture"] or tree_inventory(root) != plan["source_inventory"]:
        raise MigrationError("Frozen source no longer matches the immutable plan.")


def _target(destination: Path, source: Path, active: Path) -> os.stat_result | None:
    reject_overlap(destination, source)
    reject_overlap(destination, reject_symlink_chain(active))
    if not destination.exists():
        return None
    if not destination.is_dir() or any(destination.iterdir()):
        raise MigrationError("Candidate must be new or empty; failed attempts require a new path.")
    return destination.stat()


def _check_target(destination: Path, expected: os.stat_result | None) -> None:
    if expected is None:
        if destination.exists():
            raise MigrationError("Candidate target appeared during build.")
        return
    current = destination.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(current, field) != getattr(expected, field) for field in fields):
        raise MigrationError("Candidate target changed during build.")
    if any(destination.iterdir()):
        raise MigrationError("Candidate target is no longer empty.")


def build_migration(
    plan: Path,
    staging: Path,
    *,
    active_data_dir: Path,
    parent_attempt_id: str | None = None,
) -> MigrationResult:
    """Build a fresh attempt; only verified completed identical candidates are replayable."""
    from finjuice.pipeline.migration.verify import verify_migration

    require_mutation_platform()
    validate_attempt_id(parent_attempt_id)
    plan_path = reject_symlink_chain(plan)
    frozen = load_sealed(plan_path, PLAN_VERSION)
    if frozen.get("completion_marker") != "planned":
        raise MigrationError("Migration plan is incomplete.")
    source = reject_symlink_chain(plan_path.parent / frozen["capture_locator"])
    destination = require_outside_program_repo(staging, context="migration candidate")
    reject_overlap(source, reject_symlink_chain(active_data_dir))
    if destination.name.startswith(".migration-attempt-"):
        raise MigrationError("Attempt workspace cannot be used as a published candidate.")
    reject_overlap(destination, source)
    reject_overlap(destination, reject_symlink_chain(active_data_dir))
    reject_overlap(destination, plan_path)
    validate_source(source, frozen)
    complete = destination / "manifests" / MANIFEST
    if complete.exists():
        result = verify_migration(complete).to_dict()
        previous = load_sealed(complete, MIGRATION_VERSION)
        if previous["plan_digest"] != frozen["canonical_digest"]:
            raise MigrationError("Completed candidate belongs to a different plan.")
        fsync_parent_chain(destination.parent)
        return MigrationResult({**result, "status": "already_complete"})
    existing = _target(destination, source, active_data_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    attempt = uuid.uuid4().hex
    work = destination.parent / f".migration-attempt-{attempt}"
    work.mkdir(mode=0o700)
    try:
        _build_attempt(work, source, frozen, attempt, parent_attempt_id)
        validate_source(source, frozen)
        _check_target(destination, existing)
        evidence = load_sealed(work / "manifests" / MANIFEST, MIGRATION_VERSION)
        write_text_atomic(work / MARKER, evidence["canonical_digest"] + "\n")
        atomic_publish(work, destination, replace_empty=existing is not None)
    except BaseException:
        # Failed work remains inspectable but has no published candidate authority.
        # The caller retries at a fresh target with this attempt as its parent.
        raise
    return verify_migration(destination / "manifests" / MANIFEST)


def _build_attempt(
    work: Path,
    source: Path,
    plan: dict[str, Any],
    attempt: str,
    parent: str | None,
) -> None:
    from finjuice.pipeline.migration.verify import semantic_snapshot, verify_contents

    paths = GenerationPaths(work)
    capture = plan["capture"]
    populate_repository(source, capture, paths)
    portable_plan = plan
    write_text_atomic(paths.manifests / "plan-evidence.json", canonical(portable_plan) + "\n")
    manifest = seal(
        {
            "schema_version": MIGRATION_VERSION,
            "completion_marker": MARKER,
            "attempt_id": attempt,
            "parent_attempt_id": parent,
            "status": "inactive",
            "plan_digest": plan["canonical_digest"],
            "capture": capture,
            "capture_object_digest": file_digest(source / MANIFEST_FILENAME),
            "baseline_origin": baseline_origin(capture),
            "inputs": plan["inputs"],
            "database_digest": file_digest(paths.database),
            "semantic_digest": semantic_snapshot(paths.database),
            "plan_evidence_digest": file_digest(paths.manifests / "plan-evidence.json"),
        }
    )
    write_text_atomic(paths.manifests / MANIFEST, canonical(manifest) + "\n")
    verify_contents(work, manifest)
