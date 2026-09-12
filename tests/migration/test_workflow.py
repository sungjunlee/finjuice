"""Synthetic frozen-capture migration publication and parity tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from finjuice.pipeline.backup import (
    BackupError,
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
)
from finjuice.pipeline.migration import (
    MigrationError,
    build_migration,
    plan_migration,
    verify_migration,
)
from finjuice.pipeline.migration import build as workflow
from finjuice.pipeline.migration.common import MARKER, tree_inventory
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader


@pytest.fixture
def capture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "live"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"synthetic\x00\xff")
    (source / "empty").mkdir()
    backup = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source=source,
            output=backup,
            consistency=ConsistencyEvidence("stopped_writers", ("synthetic-test",)),
            extra_roots=(SourceRoot("optional", "optional", None),),
        )
    )
    plan = tmp_path / "plan.json"
    plan_migration(backup / "backup-manifest.json", output=plan)
    return source, backup, plan


def test_build_verify_and_retry_preserve_source(capture: tuple[Path, Path, Path], tmp_path: Path):
    source, backup, plan = capture
    original = tree_inventory(source), tree_inventory(backup)
    target = tmp_path / "candidate"
    result = build_migration(plan, target, active_data_dir=source).to_dict()
    assert result["status"] == "ok"
    assert result["cutover_ready"] is False
    assert (
        build_migration(plan, target, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    second = tmp_path / "second"
    build_migration(plan, second, active_data_dir=source)
    assert semantic_snapshot(target / "finjuice.sqlite3") == semantic_snapshot(
        second / "finjuice.sqlite3"
    )
    assert original == (tree_inventory(source), tree_inventory(backup))
    with RepositoryReader(target / "finjuice.sqlite3") as reader:
        revisions = reader.rows("config_revisions")
        assert len(revisions) == 1
        assert (
            json.loads(revisions[0]["canonical_payload_json"])["origin_kind"]
            == "legacy_current_state"
        )
        assert reader.rows("audit_events") == []
        assert reader.info.dataset_revision == 0


@pytest.mark.parametrize("change", ["modify", "add", "delete", "outside_payload"])
def test_changed_capture_rejected(capture: tuple[Path, Path, Path], tmp_path: Path, change: str):
    source, backup, plan = capture
    frozen = backup / "payload" / "data" / "opaque.bin"
    if change == "modify":
        frozen.write_bytes(b"changed")
    elif change == "add":
        (frozen.parent / "extra").write_text("new")
    elif change == "delete":
        frozen.unlink()
    else:
        (backup / "extra").write_text("new")
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, tmp_path / "candidate", active_data_dir=source)
    assert not (tmp_path / "candidate").exists()


def test_nonempty_and_active_target_rejected(capture: tuple[Path, Path, Path], tmp_path: Path):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "sentinel").write_text("keep")
    for path in (target, source, source / "child"):
        with pytest.raises((BackupError, MigrationError)):
            build_migration(plan, path, active_data_dir=source)
    assert (target / "sentinel").read_text() == "keep"


def test_failed_attempt_is_not_published(capture, tmp_path, monkeypatch):
    source, _backup, plan = capture
    real = workflow.populate_repository

    def broken(root, manifest, paths):
        real(root, manifest, paths)
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(workflow, "populate_repository", broken)
    target = tmp_path / "candidate"
    with pytest.raises(OSError, match="synthetic disk failure"):
        build_migration(plan, target, active_data_dir=source)
    assert not target.exists()
    attempts = list(tmp_path.glob(".migration-attempt-*"))
    assert len(attempts) == 1
    assert not (attempts[0] / MARKER).exists()
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, attempts[0], active_data_dir=source)


@pytest.mark.parametrize("tamper", ["marker", "database", "source_object"])
def test_candidate_tamper_rejected(capture, tmp_path, tamper):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    if tamper == "marker":
        (target / MARKER).unlink()
    elif tamper == "database":
        with sqlite3.connect(target / "finjuice.sqlite3") as connection:
            connection.execute("UPDATE repository_meta SET dataset_revision=1")
    else:
        object_path = next((target / "objects" / "sha256").glob("*/*"))
        object_path.chmod(0o600)
        object_path.write_bytes(b"tampered")
    with pytest.raises((ValueError, BackupError, RuntimeError)):
        verify_migration(target)


def test_source_change_during_build_prevents_publication(capture, tmp_path, monkeypatch):
    source, backup, plan = capture
    real = workflow.populate_repository

    def changed(root, manifest, paths):
        real(root, manifest, paths)
        if root == backup:
            (backup / "payload" / "data" / "added").write_text("race")

    monkeypatch.setattr(workflow, "populate_repository", changed)
    with pytest.raises((BackupError, MigrationError)):
        build_migration(plan, tmp_path / "candidate", active_data_dir=source)
    assert not (tmp_path / "candidate").exists()


def test_empty_target_and_missing_marker_retry(capture, tmp_path):
    source, _backup, plan = capture
    target = tmp_path / "candidate"
    target.mkdir()
    build_migration(plan, target, active_data_dir=source)
    (target / MARKER).unlink()
    with pytest.raises(MigrationError, match="completion marker"):
        build_migration(plan, target, active_data_dir=source)


def test_plan_is_immutable_and_requires_completed_capture(capture, tmp_path):
    _source, backup, plan = capture
    before = plan.read_bytes()
    with pytest.raises(BackupError):
        plan_migration(backup, output=plan)
    assert plan.read_bytes() == before
    (backup / "FINJUICE_BACKUP_COMPLETE").unlink()
    with pytest.raises(BackupError):
        plan_migration(backup, output=tmp_path / "another-plan")


def test_rehashed_database_tamper_fails_source_parity(capture, tmp_path):
    from finjuice.pipeline.migration.common import canonical, file_digest, seal

    source, _backup, plan = capture
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    with sqlite3.connect(target / "finjuice.sqlite3") as connection:
        connection.execute("UPDATE repository_meta SET dataset_revision=1")
    location = target / "manifests" / "migration-manifest.json"
    manifest = json.loads(location.read_text())
    manifest.pop("canonical_digest")
    manifest["database_digest"] = file_digest(target / "finjuice.sqlite3")
    manifest["semantic_digest"] = semantic_snapshot(target / "finjuice.sqlite3")
    manifest = seal(manifest)
    location.write_text(canonical(manifest))
    (target / MARKER).write_text(manifest["canonical_digest"] + "\n")
    with pytest.raises(MigrationError, match="differ from source"):
        verify_migration(target)
