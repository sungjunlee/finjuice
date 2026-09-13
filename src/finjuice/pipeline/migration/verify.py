"""Reconstruct frozen evidence and compare complete preservation semantics."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup import verify_backup
from finjuice.pipeline.backup.manifest import payload_relative, validate_manifest_structure
from finjuice.pipeline.backup.paths import reject_symlink_chain
from finjuice.pipeline.backup.types import COMPLETION_MARKER, MANIFEST_FILENAME
from finjuice.pipeline.migration.attempts import validate_evidence
from finjuice.pipeline.migration.common import (
    ATTEMPT_MIGRATION_VERSION,
    MANIFEST,
    MARKER,
    PLAN_VERSION,
    MigrationError,
    MigrationResult,
    canonical,
    digest,
    file_digest,
    load_migration_manifest,
    load_sealed,
)
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import migration_policy, migration_schema_version
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader, SourceObjectStore


def semantic_snapshot(database: Path, *, expected_schema_version: int | None = None) -> str:
    """Hash every repository table, excluding only schema-install wall-clock metadata."""
    state = {}
    with RepositoryReader(database, expected_schema_version=expected_schema_version) as reader:
        for table in reader.table_names:
            rows = reader.rows(table)
            if table == "schema_migrations":
                rows = [
                    {key: value for key, value in row.items() if key != "applied_at"}
                    for row in rows
                ]
            state[table] = sorted(rows, key=canonical)
    return digest(state)


def _restore_capture(paths: GenerationPaths, manifest: dict[str, Any], target: Path) -> None:
    capture = manifest["capture"]
    validate_manifest_structure(capture)
    objects = SourceObjectStore(paths)
    artifact = objects.verify(manifest["capture_object_digest"])
    shutil.copyfile(paths.root / artifact.relative_path, target / MANIFEST_FILENAME)
    original = json.loads((target / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if original != capture:
        raise MigrationError("Original capture manifest object does not match migration evidence.")
    directories = []
    for entry in capture["entries"]:
        destination = target / payload_relative(entry["root"], entry["path"])
        if entry["type"] == "directory":
            destination.mkdir(parents=True, exist_ok=True)
            directories.append((destination, entry))
        else:
            artifact = objects.verify(entry["sha256"], expected_size=entry["size"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths.root / artifact.relative_path, destination)
            _metadata(destination, entry)
    for directory, entry in sorted(directories, key=lambda pair: len(pair[0].parts), reverse=True):
        _metadata(directory, entry)
    (target / COMPLETION_MARKER).write_text(capture["canonical_digest"] + "\n", encoding="utf-8")
    verify_backup(target / MANIFEST_FILENAME)


def _metadata(path: Path, entry: dict[str, Any]) -> None:
    os.chmod(path, int(entry["mode"], 8))
    os.utime(path, ns=(entry["mtime_ns"], entry["mtime_ns"]))


def _validate_attempt_bindings(manifest: dict[str, Any], evidence: Any) -> None:
    attempt = manifest.get("attempt_id")
    plan = manifest.get("plan_digest")
    capture = manifest.get("capture")
    if not isinstance(attempt, str) or not isinstance(plan, str) or not isinstance(capture, dict):
        raise MigrationError("Candidate attempt bindings are missing or malformed.")
    capture_digest = capture.get("canonical_digest")
    if not isinstance(capture_digest, str):
        raise MigrationError("Candidate capture digest is missing or malformed.")
    validate_evidence(evidence, attempt, plan, capture_digest)


def _verify_attempt_evidence(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schema_version") == ATTEMPT_MIGRATION_VERSION
        and "attempt_evidence" not in manifest
    ):
        raise MigrationError("Migration v2 requires durable attempt evidence.")
    if (
        manifest.get("schema_version") != ATTEMPT_MIGRATION_VERSION
        and "attempt_evidence" in manifest
    ):
        raise MigrationError("Legacy manifests cannot claim attempt evidence.")
    if "attempt_evidence" in manifest:
        evidence = manifest["attempt_evidence"]
        _validate_attempt_bindings(manifest, evidence)
        if "outcome" in evidence or [record["phase"] for record in evidence["records"]] != [
            "started",
            "building",
        ]:
            raise MigrationError("Candidate attempt must contain its pre-build phase snapshot.")
        parent = evidence["records"][0].get("parent")
        actual_parent = parent["records"][0]["attempt_id"] if parent else None
        if actual_parent != manifest.get("parent_attempt_id"):
            raise MigrationError("Candidate retry parent binding does not match.")


def verify_contents(root: Path, manifest: dict[str, Any]) -> None:
    """Check candidate bytes and replay adapters solely from retained immutable evidence."""
    from finjuice.pipeline.migration.build import baseline_origin, populate_repository

    _verify_attempt_evidence(manifest)
    paths = GenerationPaths(root)
    reject_symlink_chain(paths.database)
    evidence_file = paths.manifests / "plan-evidence.json"
    plan = load_sealed(evidence_file, PLAN_VERSION)
    policy = migration_policy(plan)
    schema_version = migration_schema_version(policy)
    if (
        file_digest(paths.database) != manifest["database_digest"]
        or file_digest(evidence_file) != manifest["plan_evidence_digest"]
    ):
        raise MigrationError("Candidate database or plan evidence hash does not match.")
    if (
        plan["canonical_digest"] != manifest["plan_digest"]
        or plan["capture"] != manifest["capture"]
        or plan["inputs"] != manifest["inputs"]
        or manifest["baseline_origin"] != baseline_origin(manifest["capture"])
    ):
        raise MigrationError("Candidate capture, plan, or baseline binding does not match.")
    planned_manifest = [
        entry for entry in plan["source_inventory"] if entry["path"] == MANIFEST_FILENAME
    ]
    if (
        len(planned_manifest) != 1
        or planned_manifest[0]["sha256"] != manifest["capture_object_digest"]
    ):
        raise MigrationError("Original capture bytes do not match the immutable plan.")
    actual = semantic_snapshot(paths.database, expected_schema_version=schema_version)
    if actual != manifest["semantic_digest"]:
        raise MigrationError("Candidate repository semantic digest does not match.")
    with tempfile.TemporaryDirectory(prefix="finjuice-migration-verify-") as directory:
        scratch = Path(directory).resolve()
        capture_root = scratch / "capture"
        capture_root.mkdir()
        _restore_capture(paths, manifest, capture_root)
        if analyze_capture(capture_root, manifest["capture"], policy=policy) != manifest["inputs"]:
            raise MigrationError("Source input dispositions do not match preserved evidence.")
        expected = GenerationPaths(scratch / "expected")
        populate_repository(capture_root, manifest["capture"], expected, policy=policy)
        if semantic_snapshot(expected.database, expected_schema_version=schema_version) != actual:
            raise MigrationError(
                "Typed rows, provenance, payloads or dispositions differ from source."
            )
    if file_digest(paths.database) != manifest["database_digest"]:
        raise MigrationError("Candidate database changed during verification.")


def verify_migration(candidate: Path) -> MigrationResult:
    """Verify a complete inactive candidate without mutating its database or source tree."""
    location = reject_symlink_chain(candidate)
    manifest_path = location / "manifests" / MANIFEST if location.is_dir() else location
    if manifest_path.name != MANIFEST or manifest_path.parent.name != "manifests":
        raise MigrationError(
            "Candidate must identify its migration manifest or generation directory."
        )
    root = manifest_path.parent.parent
    if root.name.startswith(".migration-attempt-"):
        raise MigrationError("Unpublished attempt workspace is not a complete candidate.")
    manifest = load_migration_manifest(manifest_path)
    marker = reject_symlink_chain(root / MARKER)
    if (
        manifest.get("completion_marker") != MARKER
        or manifest.get("status") != "inactive"
        or not marker.is_file()
        or marker.read_text(encoding="utf-8").strip() != manifest["canonical_digest"]
    ):
        raise MigrationError("Migration completion marker is missing or mismatched.")
    before = file_digest(manifest_path)
    verify_contents(root, manifest)
    if file_digest(manifest_path) != before:
        raise MigrationError("Migration manifest changed during verification.")
    return MigrationResult(
        {
            "status": "ok",
            "phase": "migration_verify",
            "generation_status": "inactive",
            "manifest_digest": manifest["canonical_digest"],
            "attempt_id": manifest["attempt_id"],
            "origin_kind": "legacy_current_state",
            "dataset_revision": 0,
            "input_count": len(manifest["inputs"]),
            "checks": {
                "database_integrity": "passed",
                "foreign_keys": "passed",
                "object_hashes": "passed",
                "capture_reconstruction": "passed",
                "source_semantic_parity": "passed",
            },
            "cutover_ready": False,
            "limitations": [
                "No activation, consumer parity, runtime restore, or operator approval tested.",
                "Adapter replay is consistency evidence, not an independent parser oracle.",
            ],
        }
    )
