"""Pending-import preview helpers for one-shot workflow automation.

Owns import-directory preview samples, failure records, the shared signal-status
literal, and filename normalization. Tagging-pressure, large-transaction, and
next-step helpers stay in :mod:`finjuice.pipeline.automation_helpers`, which
re-exports these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.config import Config
from finjuice.pipeline.ingest.pipeline import preview_ingest_all_files

SignalStatus = Literal["present", "clear", "unavailable"]


@dataclass(frozen=True)
class PendingImportFile:
    """Preview summary for one actionable file in imports/."""

    source_file: str
    estimated_new_rows: int
    estimated_new_asset_rows: int
    validation_skips: int


@dataclass(frozen=True)
class PendingImportFailure:
    """File that could not be previewed cleanly."""

    source_file: str
    error: str


@dataclass(frozen=True)
class PendingImportsSignal:
    """Signal summarizing whether imports/ appears to need attention."""

    status: SignalStatus
    files_found: int
    pending_files: int
    estimated_new_rows: int
    estimated_new_asset_rows: int
    failed_files: list[PendingImportFailure]
    sample_files: list[PendingImportFile]


def _collect_pending_imports(
    *,
    config: Config,
    sample_limit: int,
) -> PendingImportsSignal:
    """Use ingest preview to identify actionable files still sitting in imports/."""
    preview = preview_ingest_all_files(config.import_dir, config.csv_base_dir, archive=False)

    sample_files: list[PendingImportFile] = []
    pending_file_count = 0
    estimated_new_rows = 0
    estimated_new_asset_rows = 0

    for file_summary in preview.get("files", []):
        transactions = file_summary.get("transactions", {}) or {}
        asset_snapshots = file_summary.get("asset_snapshots", {}) or {}
        tx_rows = int(transactions.get("estimated_new_rows") or 0)
        asset_rows = int(asset_snapshots.get("estimated_new_rows") or 0)
        validation_skips = int(transactions.get("validation_skips") or 0)

        if tx_rows <= 0 and asset_rows <= 0 and validation_skips <= 0:
            continue

        pending_file_count += 1
        estimated_new_rows += tx_rows
        estimated_new_asset_rows += asset_rows

        if len(sample_files) < sample_limit:
            sample_files.append(
                PendingImportFile(
                    source_file=_basename(file_summary.get("source_file")),
                    estimated_new_rows=tx_rows,
                    estimated_new_asset_rows=asset_rows,
                    validation_skips=validation_skips,
                )
            )

    failures = [
        PendingImportFailure(source_file=source_file, error=error)
        for source_file, error in preview.get("failed_files", [])
    ]
    status: SignalStatus = "present" if pending_file_count > 0 or failures else "clear"

    return PendingImportsSignal(
        status=status,
        files_found=int(preview.get("files_found") or 0),
        pending_files=pending_file_count,
        estimated_new_rows=estimated_new_rows,
        estimated_new_asset_rows=estimated_new_asset_rows,
        failed_files=failures,
        sample_files=sample_files,
    )


def _basename(value: Any) -> str:
    """Return a CLI-friendly filename for a path-like value."""
    if value is None:
        return ""
    return Path(str(value)).name
