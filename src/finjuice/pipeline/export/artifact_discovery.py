"""Discover current intact local export receipts without reading canonical data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.export.artifacts import (
    MANIFEST_NAME,
    ExportArtifactError,
    _member,
    inspect_repository_export_inventory,
)

Target = Literal["master", "reports"]
_ERROR = "Could not select a current intact repository export artifact."


@dataclass(frozen=True)
class SelectedArtifact:
    """Local receipt selection; observed order is not authenticated creation order."""

    path: Path
    manifest_path: Path
    manifest_sha256: str
    target: Target
    selection_policy: str = "current_receipt_observed_mtime.v1"


def discover_repository_artifact(
    export_root: Path, current: dict[str, object], target: Target
) -> SelectedArtifact:
    """Choose an intact current run by observed manifest mtime and stable path tie-break."""
    try:
        runs = export_root / "runs"
        if any(path.is_symlink() for path in (runs, *runs.parents)):
            raise ExportArtifactError(_ERROR)
        candidates = []
        for run in sorted(runs.iterdir()):
            if run.is_symlink():
                raise ExportArtifactError(_ERROR)
            if not run.is_dir():
                continue
            manifest = run / MANIFEST_NAME
            verification, inventory = inspect_repository_export_inventory(
                manifest, export_root, current
            )
            selected = _select_path(run, inventory, target)
            if verification["integrity"] != "intact":
                raise ExportArtifactError(_ERROR)
            if verification["stale"] or selected is None:
                continue
            selection = SelectedArtifact(
                selected, manifest, verification["manifest_sha256"], target
            )
            candidates.append((manifest.stat().st_mtime_ns, str(manifest), selection))
        if not candidates:
            raise ExportArtifactError(_ERROR)
        return max(candidates, key=lambda candidate: candidate[:2])[2]
    except Exception:
        raise ExportArtifactError(_ERROR) from None


def validate_selected_artifact(
    selection: SelectedArtifact, export_root: Path, current: dict[str, object]
) -> None:
    """Recheck the selected receipt hash and artifact integrity immediately before opening."""
    try:
        verification, inventory = inspect_repository_export_inventory(
            selection.manifest_path, export_root, current
        )
        selected = _select_path(selection.manifest_path.parent, inventory, selection.target)
        if (
            verification["stale"]
            or verification["integrity"] != "intact"
            or verification["manifest_sha256"] != selection.manifest_sha256
            or selected != selection.path
        ):
            raise ExportArtifactError(_ERROR)
    except Exception:
        raise ExportArtifactError(_ERROR) from None


def _select_path(run: Path, inventory: dict[str, Any], target: Target) -> Path | None:
    _validate_run_inventory(run, inventory)
    entries = inventory["files"]
    if any(not isinstance(entry.get("kind"), str) for entry in entries):
        raise ExportArtifactError(_ERROR)
    masters = [entry for entry in entries if entry["kind"] == "master_xlsx"]
    if len(masters) > 1:
        raise ExportArtifactError(_ERROR)
    if target == "master":
        return _member(run, masters[0]["path"]) if masters else None
    if target != "reports":
        raise ExportArtifactError(_ERROR)
    reports = [entry for entry in entries if Path(entry["path"]).parts[0] == "reports"]
    if not reports:
        return None
    destination = _member(run, "reports")
    if not destination.is_dir():
        raise ExportArtifactError(_ERROR)
    return destination


def _validate_run_inventory(run: Path, inventory: dict[str, Any]) -> None:
    declared = {entry["path"] for entry in inventory["files"]} | {MANIFEST_NAME}
    observed = set()
    for path in run.rglob("*"):
        if path.is_symlink():
            raise ExportArtifactError(_ERROR)
        if path.is_file():
            observed.add(path.relative_to(run).as_posix())
        elif not path.is_dir():
            raise ExportArtifactError(_ERROR)
    if observed != declared:
        raise ExportArtifactError(_ERROR)
