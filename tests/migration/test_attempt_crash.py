"""Actual process death distinguishes live, abandoned, and published attempts."""

from __future__ import annotations

import json
import selectors
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.migration import MigrationError, build_migration, plan_migration
from finjuice.pipeline.migration.common import MANIFEST, tree_inventory

_CHILD = """
import sys
from pathlib import Path
from finjuice.pipeline.migration import build as workflow
stage, plan, target, source = sys.argv[1:]

def pause():
    print("READY", flush=True)
    sys.stdin.readline()

if stage == "building":
    def blocked(*args, **kwargs):
        pause()
        raise RuntimeError("child should be killed")
    workflow.populate_repository = blocked
else:
    real = workflow.atomic_publish
    def published(*args, **kwargs):
        real(*args, **kwargs)
        pause()
    workflow.atomic_publish = published
workflow.build_migration(Path(plan), Path(target), active_data_dir=Path(source))
"""


def _capture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"synthetic evidence\x00")
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("synthetic",)))
    )
    plan = tmp_path / "plan.json"
    plan_migration(capture, output=plan, active_data_dir=source)
    return source, capture, plan


@contextmanager
def _paused_child(stage: str, plan: Path, target: Path, source: Path) -> Iterator[subprocess.Popen]:
    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD, stage, str(plan), str(target), str(source)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=30), "child did not reach controlled phase"
        assert process.stdout.readline().strip() == "READY"
        assert process.poll() is None
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def _attempt_id(parent: Path) -> str:
    entries = [
        item for item in (parent / ".finjuice-migration-attempts").iterdir() if item.is_dir()
    ]
    assert len(entries) == 1
    return entries[0].name


def test_killed_builder_can_only_retry_after_live_lock_releases(tmp_path: Path) -> None:
    source, capture, plan = _capture(tmp_path)
    original = tree_inventory(source), tree_inventory(capture)
    target = tmp_path / "candidate"
    retry = tmp_path / "retry"
    with _paused_child("building", plan, target, source) as process:
        parent = _attempt_id(tmp_path)
        with pytest.raises(MigrationError):
            build_migration(plan, retry, active_data_dir=source, parent_attempt_id=parent)
        assert not retry.exists()
        process.kill()
        assert process.wait(timeout=10) != 0
    abandoned = tmp_path / f".migration-attempt-{parent}"
    abandoned_before = tree_inventory(abandoned)
    with pytest.raises(MigrationError):
        build_migration(plan, target, active_data_dir=source, parent_attempt_id=parent)
    result = build_migration(plan, retry, active_data_dir=source, parent_attempt_id=parent)
    assert result.to_dict()["status"] == "ok"
    manifest = json.loads((retry / "manifests" / MANIFEST).read_text())
    assert manifest["parent_attempt_id"] == parent
    assert manifest["attempt_id"] != parent
    assert abandoned_before == tree_inventory(abandoned)
    assert original == (tree_inventory(source), tree_inventory(capture))


def test_kill_after_publish_keeps_completed_retry_and_rejects_failed_parent(tmp_path: Path) -> None:
    source, capture, plan = _capture(tmp_path)
    original = tree_inventory(source), tree_inventory(capture)
    target = tmp_path / "candidate"
    with _paused_child("published", plan, target, source) as process:
        parent = _attempt_id(tmp_path)
        process.kill()
        assert process.wait(timeout=10) != 0
    published_before = tree_inventory(target)
    assert build_migration(plan, target, active_data_dir=source).to_dict()["status"] == (
        "already_complete"
    )
    with pytest.raises(MigrationError):
        build_migration(plan, tmp_path / "retry", active_data_dir=source, parent_attempt_id=parent)
    assert tree_inventory(target) == published_before
    assert original == (tree_inventory(source), tree_inventory(capture))


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_rejects_unknown_parent_without_disclosing_private_paths(
    tmp_path: Path, json_output: bool
) -> None:
    from typer.testing import CliRunner

    from finjuice.pipeline.cli.main import app

    source, capture, plan = _capture(tmp_path)
    original = tree_inventory(source), tree_inventory(capture)
    target = tmp_path / "candidate"
    arguments = [
        "--data-dir",
        str(source),
        "ssot",
        "migrate",
        "build",
        "--plan",
        str(plan),
        "--staging",
        str(target),
        "--parent-attempt-id",
        "a" * 32,
    ]
    if json_output:
        arguments.append("--json")
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 3
    assert str(tmp_path) not in result.output
    if json_output:
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "VALIDATION_FAILED"
    else:
        assert "Migration validation failed" in result.output
    assert not target.exists()
    assert not (tmp_path / ".finjuice-migration-attempts").exists()
    assert original == (tree_inventory(source), tree_inventory(capture))


def test_new_manifest_cannot_omit_its_required_attempt_evidence(tmp_path: Path) -> None:
    from finjuice.pipeline.migration import verify_migration
    from finjuice.pipeline.migration.common import MARKER, canonical, seal

    source, _capture_path, plan = _capture(tmp_path)
    target = tmp_path / "candidate"
    build_migration(plan, target, active_data_dir=source)
    manifest_path = target / "manifests" / MANIFEST
    evidence = json.loads(manifest_path.read_text())
    assert evidence["schema_version"] == "finjuice.migration.v2"
    evidence.pop("attempt_evidence")
    evidence.pop("canonical_digest")
    tampered = seal(evidence)
    manifest_path.write_text(canonical(tampered))
    (target / MARKER).write_text(tampered["canonical_digest"] + "\n")
    with pytest.raises(MigrationError):
        verify_migration(target)


def test_parent_traversal_is_rejected_before_any_plan_or_journal_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from finjuice.pipeline.backup import BackupError
    from finjuice.pipeline.migration import build as workflow

    read = Mock(side_effect=AssertionError("must not access a path"))
    monkeypatch.setattr(workflow, "load_sealed", read)
    with pytest.raises(BackupError, match="32 lowercase hexadecimal"):
        build_migration(
            tmp_path / "absent-plan",
            tmp_path / "candidate",
            active_data_dir=tmp_path / "source",
            parent_attempt_id="../../outside",
        )
    read.assert_not_called()
    assert list(tmp_path.iterdir()) == []
