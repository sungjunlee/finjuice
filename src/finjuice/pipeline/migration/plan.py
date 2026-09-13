"""Read verified M1 captures and freeze deterministic preservation plans."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from finjuice.pipeline.backup import verify_backup
from finjuice.pipeline.backup.io import fsync_parent_chain, write_text_atomic
from finjuice.pipeline.backup.manifest import backup_dir_from_manifest_path, payload_relative
from finjuice.pipeline.backup.paths import (
    reject_overlap,
    reject_symlink_chain,
    require_outside_program_repo,
)
from finjuice.pipeline.backup.types import COMPLETION_MARKER, DATA_ROOT_NAME, MANIFEST_FILENAME
from finjuice.pipeline.migration.adapters import FileContext, analyze_file
from finjuice.pipeline.migration.adapters.csv_rows import rows
from finjuice.pipeline.migration.adapters.model import Emitter
from finjuice.pipeline.migration.adapters.overview_reports import report_role
from finjuice.pipeline.migration.common import (
    PLAN_VERSION,
    MigrationError,
    MigrationResult,
    canonical,
    seal,
    tree_inventory,
)
from finjuice.pipeline.migration.policy import (
    CONFIG_HEAD_POLICY,
    LEGACY_POLICY,
    MANUAL_STATE_POLICY,
    OVERVIEW_REPORT_POLICY,
)


def file_context(
    capture: dict[str, Any],
    entry: dict[str, Any],
    *,
    policy: str = LEGACY_POLICY,
    fact_index: tuple[tuple[str, str, str], ...] = (),
) -> FileContext:
    version = capture.get("data_schema_version")
    return FileContext(
        capture["canonical_digest"].removeprefix("sha256:"),
        entry["root"],
        entry["path"],
        None if version is None else str(version),
        capture["capture"]["completed_at"]
        if policy in (CONFIG_HEAD_POLICY, MANUAL_STATE_POLICY, OVERVIEW_REPORT_POLICY)
        and entry["root"] == DATA_ROOT_NAME
        and entry["path"] in {"rules.yaml", "goals.yaml"}
        else None,
        policy,
        fact_index,
    )


def capture_fact_index(
    root: Path, capture: dict[str, Any], *, policy: str
) -> tuple[tuple[str, str, str], ...]:
    """Index original mapped fact rows, including those with invalid typed values."""
    if policy != OVERVIEW_REPORT_POLICY:
        return ()
    result = []
    for entry in capture["entries"]:
        if entry["type"] != "file" or not entry["path"].lower().endswith(".csv"):
            continue
        if (
            "transactions" in PurePosixPath(entry["path"]).parts
            or report_role(entry["path"]) is not None
        ):
            continue
        source = root / payload_relative(entry["root"], entry["path"])
        emitter = Emitter(file_context(capture, entry, policy=policy), None)
        try:
            for ordinal, _payload, row in rows(source.read_bytes()):
                if row is not None and "fact_id" in row and "fact_kind" in row:
                    alias = row["fact_id"]
                    if alias is not None:
                        emitter.row = ordinal
                        result.append(
                            (
                                alias,
                                emitter.identifier("observation"),
                                emitter.identifier("provenance"),
                            )
                        )
        except (UnicodeError, csv.Error):
            # Earlier valid rows are emitted by the same streaming parser during build.
            continue
    return tuple(result)


def analyze_capture(
    root: Path, capture: dict[str, Any], *, policy: str = LEGACY_POLICY
) -> list[dict[str, Any]]:
    inputs = []
    fact_index = capture_fact_index(root, capture, policy=policy)
    for entry in capture["entries"]:
        item = {"root": entry["root"], "path": entry["path"], "type": entry["type"]}
        if entry["type"] == "file":
            source = root / payload_relative(entry["root"], entry["path"])
            item["analysis"] = analyze_file(
                source, file_context(capture, entry, policy=policy, fact_index=fact_index)
            ).to_dict()
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
            "migration_policy": OVERVIEW_REPORT_POLICY,
            "completion_marker": "planned",
            "capture_locator": Path(os.path.relpath(root, base)).as_posix(),
            "capture": capture,
            "source_inventory": before,
            "inputs": analyze_capture(root, capture, policy=OVERVIEW_REPORT_POLICY),
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
