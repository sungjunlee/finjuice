"""Read verified M1 captures and freeze deterministic preservation plans."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup import verify_backup
from finjuice.pipeline.backup.io import fsync_parent_chain, write_text_atomic
from finjuice.pipeline.backup.manifest import backup_dir_from_manifest_path, payload_relative
from finjuice.pipeline.backup.paths import (
    reject_overlap,
    reject_symlink_chain,
    require_outside_program_repo,
)
from finjuice.pipeline.backup.types import COMPLETION_MARKER, MANIFEST_FILENAME
from finjuice.pipeline.migration.adapters import FileContext, analyze_file
from finjuice.pipeline.migration.common import (
    PLAN_VERSION,
    MigrationError,
    MigrationResult,
    canonical,
    seal,
    tree_inventory,
)


def file_context(capture: dict[str, Any], entry: dict[str, Any]) -> FileContext:
    version = capture.get("data_schema_version")
    return FileContext(
        capture["canonical_digest"].removeprefix("sha256:"),
        entry["root"],
        entry["path"],
        None if version is None else str(version),
    )


def analyze_capture(root: Path, capture: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = []
    for entry in capture["entries"]:
        item = {"root": entry["root"], "path": entry["path"], "type": entry["type"]}
        if entry["type"] == "file":
            source = root / payload_relative(entry["root"], entry["path"])
            item["analysis"] = analyze_file(source, file_context(capture, entry)).to_dict()
        else:
            item.update(disposition="migrated", reason="Directory inventory preserved.")
        inputs.append(item)
    for entry in capture["roots"]:
        if entry["state"] == "intentionally_absent":
            inputs.append(
                {
                    "root": entry["name"],
                    "path": ".",
                    "type": "absent",
                    "disposition": "intentionally_absent",
                    "reason": "Optional absence recorded by the verified capture.",
                }
            )
    return inputs


def plan_migration(
    manifest: Path,
    *,
    output: Path | None = None,
    active_data_dir: Path | None = None,
) -> MigrationResult:
    """Plan from a verified capture; saving requires an explicit active-data boundary."""
    location = reject_symlink_chain(manifest)
    root = backup_dir_from_manifest_path(location)
    if output is not None:
        if active_data_dir is None:
            raise MigrationError("Active data directory is required when saving a migration plan.")
        output = require_outside_program_repo(output, context="migration plan")
        reject_overlap(root, output)
        reject_overlap(reject_symlink_chain(active_data_dir), output)
    verify_backup(location)
    before = tree_inventory(root)
    capture = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    allowed = {MANIFEST_FILENAME, COMPLETION_MARKER}
    if any(item["path"].split("/")[0] not in allowed | {"payload"} for item in before):
        raise MigrationError("Capture contains files outside the closed M1 inventory.")
    base = Path.cwd() if output is None else output.parent
    plan = seal(
        {
            "schema_version": PLAN_VERSION,
            "completion_marker": "planned",
            "capture_locator": Path(os.path.relpath(root, base)).as_posix(),
            "capture": capture,
            "source_inventory": before,
            "inputs": analyze_capture(root, capture),
        }
    )
    verify_backup(location)
    if before != tree_inventory(root):
        raise MigrationError("Frozen source changed while planning.")
    if output is not None:
        write_text_atomic(output, canonical(plan) + "\n")
        fsync_parent_chain(output.parent)
    return MigrationResult(
        {
            "status": "ok",
            "phase": "migration_plan",
            "manifest_digest": plan["canonical_digest"],
            "input_count": len(plan["inputs"]),
            "plan": plan,
        }
    )
