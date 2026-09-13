"""Observe staged workbooks separately from pinned canonical import evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import import (
    ExactImportCommand,
    ExactWorkbookCapture,
    capture_exact_xlsx,
)
from finjuice.pipeline.storage.sqlite.exact_import.preview import (
    ImportPreviewSnapshot,
    preview_captured_import,
)


class StagedImportObservationError(ValueError):
    """A static error when staged input inventory cannot be observed."""


@dataclass(frozen=True)
class StagedImportObservation:
    """Captured bytes and private lookup digests; metadata contains aggregates only."""

    captures: tuple[ExactWorkbookCapture, ...]
    digests: tuple[str, ...]
    metadata: dict[str, object]
    seen_files: int
    capture_failed_files: int


@dataclass(frozen=True)
class StagedImportSummary:
    """File-level actionable results against one independent baseline revision."""

    pending_files: int
    failed_files: int
    metadata: dict[str, object]
    warning: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def capture_staged_imports(import_dir: Path, *, fast: bool = False) -> StagedImportObservation:
    """Capture every staged XLSX once, or observe names only in fast mode."""
    started = _now()
    directory_state = "present"
    try:
        paths = sorted(path for path in import_dir.iterdir() if path.suffix == ".xlsx")
    except FileNotFoundError:
        paths = []
        directory_state = "absent"
    except OSError:
        raise StagedImportObservationError(
            "Staged import inventory could not be observed."
        ) from None
    captures: list[ExactWorkbookCapture] = []
    failures = 0
    if not fast:
        for path in paths:
            try:
                captures.append(capture_exact_xlsx(path))
            except Exception:
                failures += 1
    digests = tuple(sorted({capture.digest_hex for capture in captures}))
    metadata: dict[str, object] = {
        "authority": "observed_staged_files",
        "directory_state": directory_state,
        "observation_started_at": started,
        "observation_completed_at": _now(),
        "preview_policy": "independent_baseline.v1",
        "capture_policy": "single_capture_bytes.v1",
        "fast": fast,
        "files_seen": len(paths),
        "files_examined": 0 if fast else len(paths),
        "files_not_examined": len(paths) if fast else 0,
        "files_captured": len(captures),
        "capture_failed_files": failures,
        "unique_digest_count": len(digests),
    }
    return StagedImportObservation(tuple(captures), digests, metadata, len(paths), failures)


def summarize_staged_imports(
    observation: StagedImportObservation, snapshot: ImportPreviewSnapshot
) -> StagedImportSummary:
    """Summarize independent per-file previews without reopening files or storage."""
    pending = observation.seen_files if observation.metadata["fast"] else 0
    failed = observation.capture_failed_files
    reused = 0
    codes: Counter[str] = Counter()
    if failed:
        codes["capture_failed"] = failed
    for capture in observation.captures:
        try:
            result = preview_captured_import(
                ExactImportCommand(capture, preview=True), snapshot
            ).result
        except MutationValidationError:
            # Invalid/absent canonical lookup evidence must fail the entire bundle.
            raise
        except MutationConflictError:
            codes["interpretation_conflict"] += 1
            failed += 1
            continue
        except Exception:
            codes["mapping_failed"] += 1
            failed += 1
            continue
        if result.get("noop") is True:
            reused += 1
        else:
            # Evidence-only and empty new workbooks still require an import occurrence.
            pending += 1
    metadata = {
        **observation.metadata,
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "pending_files": pending,
        "failed_files": failed,
        "already_imported_files": reused,
        "failure_codes": dict(sorted(codes.items())),
    }
    warning = "Some staged imports could not be previewed." if failed else None
    if observation.metadata["fast"]:
        warning = "Staged workbook contents were not examined in fast mode."
    return StagedImportSummary(pending, failed, metadata, warning)
