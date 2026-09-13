"""Publish isolated repository exports and check their revision and file digests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from finjuice.pipeline.export.result_helpers import _REPORT_OUTPUTS, build_output_entry

MANIFEST_NAME = "export-manifest.json"
MANIFEST_VERSION = 1


class ExportArtifactError(ValueError):
    """An export manifest or its bounded artifact paths are invalid."""


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or any(p in {".", ".."} for p in path.parts):
        raise ExportArtifactError("Invalid export artifact path.")
    target = root / path
    if any(part.is_symlink() for part in (target, *target.parents)):
        raise ExportArtifactError("Export artifact paths cannot use symbolic links.")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ExportArtifactError("Export artifact escapes its run directory.")
    return target


def _relative(path: str, root: Path) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError as exc:
        raise ExportArtifactError("Export artifact is outside its staging directory.") from exc


def publish_repository_export(
    staging_root: Path,
    export_root: Path,
    result: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Atomically publish one complete run; never reuse earlier output files.

    The manifest is a regenerable local receipt, not an authenticated ledger record.
    Relative paths and content digests are stable across equivalent export runs.
    """
    result = _describe_absent_xlsx(result, staging_root, metadata)
    entries: list[dict[str, Any]] = []
    for item in result["output_files"]:
        relative = _relative(item["path"], staging_root)
        path = _member(staging_root, relative)
        if not path.is_file():
            raise ExportArtifactError("A reported export file was not generated.")
        entries.append(
            {
                "path": relative,
                "kind": item["kind"],
                "sha256": _digest(path),
                "size_bytes": path.stat().st_size,
                "row_count": item.get("row_count"),
            }
        )
    if len({item["path"] for item in entries}) != len(entries):
        raise ExportArtifactError("Duplicate export artifact path.")
    declared = {item["path"] for item in entries}
    actual = {
        path.relative_to(staging_root).as_posix()
        for path in staging_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != declared:
        raise ExportArtifactError("Export contains unreported artifacts.")
    skipped = [
        {**item, "path": _relative(item["path"], staging_root)}
        for item in result["skipped_outputs"]
    ]
    for item in skipped:
        _member(staging_root, item["path"])
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "source": metadata,
        "files": sorted(entries, key=lambda item: item["path"]),
        "skipped_outputs": skipped,
    }
    (staging_root / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    runs = export_root / "runs"
    if any(part.is_symlink() for part in (runs, *runs.parents)):
        raise ExportArtifactError("Export destination cannot use symbolic links.")
    runs.mkdir(parents=True, exist_ok=True)
    destination = runs / str(uuid4())
    staging_root.rename(destination)
    published = dict(result)
    for key in ("output_files", "skipped_outputs"):
        published[key] = [
            {
                **item,
                "path": str(destination / _relative(item["path"], staging_root)),
                "would_overwrite": False,
            }
            for item in result[key]
        ]
    published["manifest_path"] = str(destination / MANIFEST_NAME)
    published["manifest_sha256"] = _digest(destination / MANIFEST_NAME)
    published["_repository_meta"] = metadata
    return published


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("manifest_version")) is not int
        or manifest["manifest_version"] != MANIFEST_VERSION
    ):
        raise ExportArtifactError("Unsupported export manifest.")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("authority") != "repository":
        raise ExportArtifactError("Invalid export source identity.")
    try:
        UUID(source["dataset_generation"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ExportArtifactError("Invalid export source generation.") from exc
    revision = source.get("dataset_revision")
    if type(revision) is not int or revision < 0:
        raise ExportArtifactError("Invalid export source revision.")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ExportArtifactError("Invalid export file inventory.")
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ExportArtifactError("Invalid export file entry.")
        path, digest = entry.get("path"), entry.get("sha256")
        size = entry.get("size_bytes")
        if (
            not isinstance(path, str)
            or path in seen
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or type(size) is not int
            or size < 0
        ):
            raise ExportArtifactError("Invalid export file evidence.")
        seen.add(path)
    return manifest


def inspect_repository_export(
    manifest_path: Path,
    export_root: Path,
    current: dict[str, object],
) -> dict[str, Any]:
    """Compare a saved receipt with current authority and actual artifact bytes.

    The two independent results distinguish stale data from changed/missing files.
    A matching receipt is not proof against coordinated edits to files and manifest.
    """
    runs = export_root.resolve() / "runs"
    path = manifest_path.absolute()
    if path.name != MANIFEST_NAME or not path.parent.parent.resolve() == runs:
        raise ExportArtifactError("Select a manifest inside this dataset's export runs.")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ExportArtifactError("Export manifest cannot use symbolic links.")
    manifest = _validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    files = []
    for entry in manifest["files"]:
        target = _member(path.parent, entry["path"])
        status = "missing"
        if target.exists():
            status = (
                "intact"
                if target.is_file()
                and target.stat().st_size == entry["size_bytes"]
                and _digest(target) == entry["sha256"]
                else "modified"
            )
        files.append({"path": entry["path"], "status": status})
    source = manifest["source"]
    stale = any(
        source.get(key) != current.get(key)
        for key in ("authority", "dataset_generation", "dataset_revision", "sqlite_schema_version")
    )
    return {
        "command": "export",
        "operation": "verify_manifest",
        "manifest_path": str(path),
        "manifest_sha256": _digest(path),
        "source": source,
        "current": current,
        "stale": stale,
        "integrity": "intact" if all(f["status"] == "intact" for f in files) else "mismatch",
        "files": files,
        "verification_policy": "local_export_receipt.v1",
    }


def _describe_absent_xlsx(
    result: dict[str, Any], staging: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Account for requested zero-row outputs that intentionally create no file."""
    if metadata.get("format") not in {"xlsx", "all"}:
        return result
    result = {**result, "skipped_outputs": list(result["skipped_outputs"])}
    suffix = str(metadata.get("calculation_as_of") or "undated").replace("-", "")
    requested = [(Path(f"master_{suffix}.xlsx"), "master_xlsx")]
    requested.extend((Path("reports") / name, kind) for name, kind in _REPORT_OUTPUTS)
    reported = {item["kind"] for item in result["output_files"] + result["skipped_outputs"]}
    for path, kind in requested:
        if kind not in reported:
            result["skipped_outputs"].append(
                build_output_entry(
                    staging / path,
                    kind,
                    available=False,
                    reason="No artifact produced for this output.",
                )
            )
    return result
