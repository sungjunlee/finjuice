"""Current local receipts drive artifact discovery and final revalidation."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.export.artifact_discovery import (
    discover_repository_artifact,
    validate_selected_artifact,
)
from finjuice.pipeline.export.artifacts import ExportArtifactError, inspect_repository_export

CURRENT = {
    "authority": "repository",
    "dataset_generation": "a8bc82cb-7032-4232-92e8-dca2d65e0f8b",
    "dataset_revision": 3,
    "sqlite_schema_version": 5,
}


def _run(root: Path, *, revision: int = 3, files=None) -> Path:
    run = root / "runs" / str(uuid4())
    run.mkdir(parents=True)
    files = files if files is not None else [("master_20260101.xlsx", "master_xlsx")]
    entries = []
    for filename, kind in files:
        path = run / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic artifact")
        entries.append(
            {
                "path": filename,
                "kind": kind,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = run / "export-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "source": {**CURRENT, "dataset_revision": revision},
                "files": entries,
            }
        )
    )
    return manifest


def test_current_receipt_and_observed_order(tmp_path: Path) -> None:
    older, newer = _run(tmp_path), _run(tmp_path)
    os.utime(older, ns=(100, 100))
    os.utime(newer, ns=(200, 200))
    (tmp_path / "master_99999999.xlsx").write_bytes(b"legacy")
    selection = discover_repository_artifact(tmp_path, CURRENT, "master")
    assert selection.manifest_path == newer
    assert selection.path.parent == newer.parent
    validate_selected_artifact(selection, tmp_path, CURRENT)
    assert inspect_repository_export(newer, tmp_path, CURRENT)["integrity"] == "intact"
    os.utime(older, ns=(200, 200))
    tied = discover_repository_artifact(tmp_path, CURRENT, "master")
    assert tied.manifest_path == max((older, newer), key=str)


def test_reports_and_master_are_distinct(tmp_path: Path) -> None:
    receipt = _run(tmp_path, files=[("reports/month.csv", "monthly_report")])
    selection = discover_repository_artifact(tmp_path, CURRENT, "reports")
    assert selection.path == receipt.parent / "reports"
    validate_selected_artifact(selection, tmp_path, CURRENT)
    with pytest.raises(ExportArtifactError):
        discover_repository_artifact(tmp_path, CURRENT, "master")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes require POSIX")
def test_unreported_special_file_rejects_discovery(tmp_path: Path) -> None:
    receipt = _run(tmp_path)
    os.mkfifo(receipt.parent / "unexpected-pipe")

    with pytest.raises(ExportArtifactError):
        discover_repository_artifact(tmp_path, CURRENT, "master")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes require POSIX")
def test_manifest_pipe_is_rejected_before_reading(tmp_path: Path, monkeypatch) -> None:
    receipt = _run(tmp_path)
    receipt.unlink()
    os.mkfifo(receipt)
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        assert path != receipt, "A non-regular manifest must not be opened"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(ExportArtifactError, match="regular file"):
        inspect_repository_export(receipt, tmp_path, CURRENT)
    with pytest.raises(ExportArtifactError):
        discover_repository_artifact(tmp_path, CURRENT, "master")


@pytest.mark.parametrize("case", ["absent", "stale", "empty", "legacy"])
def test_no_eligible_current_artifact(tmp_path: Path, case: str) -> None:
    if case == "stale":
        _run(tmp_path, revision=2)
    elif case == "empty":
        _run(tmp_path, files=[])
    elif case == "legacy":
        (tmp_path / "master_20260101.xlsx").write_bytes(b"legacy")
    with pytest.raises(ExportArtifactError, match="^Could not select a current intact"):
        discover_repository_artifact(tmp_path, CURRENT, "master")


@pytest.mark.parametrize(
    "case", ["syntax", "missing", "modified", "duplicate", "symlink", "traversal"]
)
def test_corrupt_candidates_fail_even_with_other_current_run(tmp_path: Path, case: str) -> None:
    _run(tmp_path)
    files = (
        [("one.xlsx", "master_xlsx"), ("two.xlsx", "master_xlsx")] if case == "duplicate" else None
    )
    bad = _run(tmp_path, revision=2, files=files)
    member = bad.parent / "master_20260101.xlsx"
    if case == "syntax":
        bad.write_text("PRIVATE_BAD[")
    elif case == "missing":
        member.unlink()
    elif case == "modified":
        member.write_bytes(b"PRIVATE_BAD")
    elif case == "symlink":
        original = bad.parent / "other"
        member.rename(original)
        member.symlink_to(original)
    elif case == "traversal":
        data = json.loads(bad.read_text())
        data["files"][0]["path"] = "../PRIVATE_BAD"
        bad.write_text(json.dumps(data))
    with pytest.raises(ExportArtifactError) as caught:
        discover_repository_artifact(tmp_path, CURRENT, "master")
    assert "PRIVATE_BAD" not in str(caught.value)


@pytest.mark.parametrize("mutation", ["receipt", "file", "revision", "symlink"])
def test_final_recheck_rejects_changes(tmp_path: Path, mutation: str) -> None:
    receipt = _run(tmp_path)
    selection = discover_repository_artifact(tmp_path, CURRENT, "master")
    current = CURRENT
    if mutation == "receipt":
        receipt.write_text(receipt.read_text() + "\n")
    elif mutation == "file":
        selection.path.write_bytes(b"changed")
    elif mutation == "revision":
        current = {**CURRENT, "dataset_revision": 4}
    else:
        destination = receipt.parent / "original"
        receipt.rename(destination)
        receipt.symlink_to(destination)
    with pytest.raises(ExportArtifactError):
        validate_selected_artifact(selection, tmp_path, current)


def test_undeclared_report_is_not_opened(tmp_path: Path) -> None:
    receipt = _run(tmp_path, files=[("reports/month.csv", "monthly_report")])
    selection = discover_repository_artifact(tmp_path, CURRENT, "reports")
    (receipt.parent / "reports/private-extra.csv").write_bytes(b"extra")
    with pytest.raises(ExportArtifactError):
        validate_selected_artifact(selection, tmp_path, CURRENT)
    with pytest.raises(ExportArtifactError):
        discover_repository_artifact(tmp_path, CURRENT, "reports")


def test_symlink_run_is_rejected(tmp_path: Path) -> None:
    receipt = _run(tmp_path)
    (tmp_path / "runs/alias").symlink_to(receipt.parent, target_is_directory=True)
    with pytest.raises(ExportArtifactError):
        discover_repository_artifact(tmp_path, CURRENT, "master")
