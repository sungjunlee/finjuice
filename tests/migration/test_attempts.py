"""Durable failed attempts and portable retry lineage use frozen synthetic inputs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.migration import (
    attempts,
    build,
    build_migration,
    plan_migration,
    verify_migration,
)
from finjuice.pipeline.migration.common import (
    MANIFEST,
    MARKER,
    MigrationError,
    canonical,
    seal,
    tree_inventory,
)


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_text("rules: []\n", encoding="utf-8")
    capture = tmp_path / "capture"
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan = tmp_path / "plan.json"
    plan_migration(capture, output=plan, active_data_dir=source)
    return source, plan


def _failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path, plan: Path) -> str:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("private details must not be journaled")

    with monkeypatch.context() as scoped:
        scoped.setattr(build, "populate_repository", fail)
        with pytest.raises(OSError):
            build_migration(plan, tmp_path / "failed", active_data_dir=source)
    journal = tmp_path / attempts.JOURNAL
    return next(journal.iterdir()).name


def test_failed_attempt_retry_portable_and_original_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan = _inputs(tmp_path)
    before = tree_inventory(source), tree_inventory(tmp_path / "capture")
    parent = _failed(tmp_path, monkeypatch, source, plan)
    original_journal = tree_inventory(tmp_path / attempts.JOURNAL / parent)
    candidate = tmp_path / "retry"
    build_migration(plan, candidate, active_data_dir=source, parent_attempt_id=parent)
    assert tree_inventory(tmp_path / attempts.JOURNAL / parent) == original_journal
    assert (tree_inventory(source), tree_inventory(tmp_path / "capture")) == before
    manifest = json.loads((candidate / "manifests" / MANIFEST).read_text())
    evidence = manifest["attempt_evidence"]["records"][0]["parent"]
    assert evidence["outcome"] == "failed"
    assert evidence["records"][-1]["error_class"] == "OSError"
    assert "private details" not in json.dumps(evidence)
    copied = tmp_path / "portable" / "copy"
    shutil.copytree(candidate, copied)
    shutil.rmtree(tmp_path / attempts.JOURNAL)
    assert verify_migration(copied).to_dict()["status"] == "ok"
    previous = tree_inventory(copied)
    assert (
        build_migration(plan, copied, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    assert tree_inventory(copied) == previous


@pytest.mark.parametrize("case", ["unknown", "tampered", "plan", "same_target", "unlinked_reuse"])
def test_retry_rejects_invalid_parent_or_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    source, plan = _inputs(tmp_path)
    parent = _failed(tmp_path, monkeypatch, source, plan)
    target = tmp_path / "retry"
    if case == "unknown":
        parent = "0" * 32
    elif case == "tampered":
        path = tmp_path / attempts.JOURNAL / parent / "0000.json"
        payload = json.loads(path.read_text())
        payload["target"] = "different"
        path.write_text(json.dumps(payload))
    elif case == "plan":
        extra = tmp_path / "other"
        extra.mkdir()
        _, plan = _inputs(extra)
    else:
        target = tmp_path / "failed"
    with pytest.raises(MigrationError):
        build_migration(
            plan,
            target,
            active_data_dir=source,
            parent_attempt_id=None if case == "unlinked_reuse" else parent,
        )
    assert not target.exists()


def test_successful_parent_and_conflicting_completed_parent_rejected(tmp_path: Path) -> None:
    source, plan = _inputs(tmp_path)
    candidate = tmp_path / "complete"
    build_migration(plan, candidate, active_data_dir=source)
    parent = next((tmp_path / attempts.JOURNAL).iterdir()).name
    with pytest.raises(MigrationError):
        build_migration(plan, tmp_path / "retry", active_data_dir=source, parent_attempt_id=parent)
    with pytest.raises(MigrationError):
        build_migration(plan, candidate, active_data_dir=source, parent_attempt_id=parent)


def test_failed_terminal_journal_write_preserves_initial_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan = _inputs(tmp_path)
    before = tree_inventory(source)
    original = attempts._publish

    def fail_terminal(path: Path, record: dict[str, object]) -> None:
        if record["phase"] == "failed":
            raise OSError(28, "No space")
        original(path, record)

    monkeypatch.setattr(attempts, "_publish", fail_terminal)
    parent = _failed(tmp_path, monkeypatch, source, plan)
    records = attempts._read(tmp_path / attempts.JOURNAL / parent)
    assert [record["phase"] for record in records] == ["started", "building"]
    monkeypatch.undo()
    build_migration(plan, tmp_path / "retry", active_data_dir=source, parent_attempt_id=parent)
    assert tree_inventory(source) == before


def test_journal_fsync_failure_does_not_replace_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan = _inputs(tmp_path)

    def fail_population(*args: object, **kwargs: object) -> None:
        def fail_fsync(path: Path) -> None:
            raise BackupError("Disk failure", code="FILE_ACCESS_ERROR")

        monkeypatch.setattr(attempts, "fsync_parent_chain", fail_fsync)
        raise RuntimeError("original failure")

    monkeypatch.setattr(build, "populate_repository", fail_population)
    with pytest.raises(RuntimeError, match="original failure"):
        build_migration(plan, tmp_path / "failed", active_data_dir=source)
    directory = next((tmp_path / attempts.JOURNAL).iterdir())
    assert (directory / "0000.json").is_file()
    assert [record["phase"] for record in attempts._read(directory)] == [
        "started",
        "building",
        "failed",
    ]


@pytest.mark.parametrize("kind", ["symlink", "reserved"])
def test_journal_path_isolation(tmp_path: Path, kind: str) -> None:
    source, plan = _inputs(tmp_path)
    before = tree_inventory(source)
    target = tmp_path / "candidate"
    if kind == "symlink":
        (tmp_path / attempts.JOURNAL).symlink_to(source, target_is_directory=True)
    else:
        target = tmp_path / attempts.JOURNAL / "candidate"
    with pytest.raises((MigrationError, BackupError)):
        build_migration(plan, target, active_data_dir=source)
    assert tree_inventory(source) == before


@pytest.mark.parametrize("mode", ["failed", "outcome", "null", "verified"])
def test_candidate_rejects_resealed_invalid_own_attempt(tmp_path: Path, mode: str) -> None:
    source, plan = _inputs(tmp_path)
    candidate = tmp_path / "candidate"
    build_migration(plan, candidate, active_data_dir=source)
    path = candidate / "manifests" / MANIFEST
    manifest = json.loads(path.read_text())
    evidence = manifest["attempt_evidence"]
    if mode == "null":
        manifest["attempt_evidence"] = None
    elif mode == "outcome":
        evidence["outcome"] = "interrupted"
    else:
        phases = (
            ["failed"] if mode == "failed" else ["built", "publishing", "published", "verified"]
        )
        for phase in phases:
            records = evidence["records"]
            records.append(
                seal(
                    {
                        "schema_version": attempts.VERSION,
                        "sequence": len(records),
                        "phase": phase,
                        "previous_digest": records[-1]["canonical_digest"],
                    }
                )
            )
    manifest.pop("canonical_digest")
    updated = seal(manifest)
    path.write_text(canonical(updated) + "\n")
    (candidate / MARKER).write_text(updated["canonical_digest"] + "\n")
    with pytest.raises(MigrationError):
        verify_migration(candidate)


@pytest.mark.parametrize("field", ["attempt_id", "plan_digest", "capture", "capture_digest"])
@pytest.mark.parametrize("mutation", ["missing", "wrong_type"])
def test_candidate_rejects_malformed_attempt_bindings(
    tmp_path: Path, field: str, mutation: str
) -> None:
    source, plan = _inputs(tmp_path)
    candidate = tmp_path / "candidate"
    build_migration(plan, candidate, active_data_dir=source)
    path = candidate / "manifests" / MANIFEST
    manifest = json.loads(path.read_text())
    owner = manifest["capture"] if field == "capture_digest" else manifest
    key = "canonical_digest" if field == "capture_digest" else field
    if mutation == "missing":
        owner.pop(key)
    else:
        owner[key] = []
    manifest.pop("canonical_digest")
    updated = seal(manifest)
    path.write_text(canonical(updated) + "\n")
    (candidate / MARKER).write_text(updated["canonical_digest"] + "\n")
    with pytest.raises(MigrationError):
        verify_migration(candidate)


def test_transient_phase_fsync_failure_retains_failure_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan = _inputs(tmp_path)
    original = attempts.fsync_parent_chain
    calls = 0

    def fail_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise BackupError("transient fsync failure", code="FILE_ACCESS_ERROR")
        original(path)

    monkeypatch.setattr(attempts, "fsync_parent_chain", fail_once)
    with pytest.raises(BackupError, match="transient fsync failure"):
        build_migration(plan, tmp_path / "failed", active_data_dir=source)
    directory = next((tmp_path / attempts.JOURNAL).iterdir())
    assert [record["phase"] for record in attempts._read(directory)] == [
        "started",
        "building",
        "failed",
    ]


def test_close_errors_preserve_unwinding_exception_and_raise_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = object.__new__(attempts.AttemptJournal)
    journal.fd = -1

    def fail_close(fd: int) -> None:
        raise OSError("close failure")

    monkeypatch.setattr(attempts.os, "close", fail_close)
    with pytest.raises(RuntimeError, match="original"):
        try:
            raise RuntimeError("original")
        finally:
            journal.close()
    with pytest.raises(OSError, match="close failure"):
        journal.close()


@pytest.mark.parametrize("error", [RuntimeError("journal"), TypeError("journal")])
def test_terminal_journal_programming_error_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    source, plan = _inputs(tmp_path)
    original = attempts._publish

    def fail_terminal(path: Path, record: dict[str, object]) -> None:
        if record["phase"] == "failed":
            raise error
        original(path, record)

    monkeypatch.setattr(attempts, "_publish", fail_terminal)
    parent = _failed(tmp_path, monkeypatch, source, plan)
    assert [record["phase"] for record in attempts._read(tmp_path / attempts.JOURNAL / parent)] == [
        "started",
        "building",
    ]


def test_phase_reconciliation_never_accepts_or_overwrites_unmatched_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, plan_path = _inputs(tmp_path)
    plan = json.loads(plan_path.read_text())
    journal = attempts.AttemptJournal(
        tmp_path / attempts.JOURNAL, "a" * 32, tmp_path / "candidate", plan, None
    )
    original = attempts._publish

    def write_unmatched(path: Path, record: dict[str, object]) -> None:
        modified = {key: value for key, value in record.items() if key != "canonical_digest"}
        modified["phase"] = "failed"
        original(path, seal(modified))
        raise OSError("publication failure")

    monkeypatch.setattr(attempts, "_publish", write_unmatched)
    try:
        with pytest.raises(OSError, match="publication failure"):
            journal.append("building")
        assert [record["phase"] for record in journal.records] == ["started"]
        path = journal.directory / "0001.json"
        before = path.read_bytes()
        journal.failure(RuntimeError("original"))
        assert path.read_bytes() == before
        assert [record["phase"] for record in journal.records] == ["started"]
    finally:
        journal.close()
