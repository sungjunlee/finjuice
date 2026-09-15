"""Observe staged workbooks separately from pinned canonical import evidence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.statements.staged import StatementCapture, capture_statement
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
class StagedImportCaptureFailure:
    """Private original basename and a static capture failure code."""

    filename: str
    failure_code: str = "capture_failed"


@dataclass(frozen=True)
class StagedImportObservation:
    """Captured bytes and private lookup digests; metadata contains aggregates only."""

    captures: tuple[ExactWorkbookCapture, ...]
    digests: tuple[str, ...]
    metadata: dict[str, object]
    seen_files: int
    capture_failed_files: int
    capture_failures: tuple[StagedImportCaptureFailure, ...] = ()
    statements: tuple[StatementCapture, ...] = ()


@dataclass(frozen=True)
class StagedImportSummary:
    """File-level actionable results against one independent baseline revision."""

    pending_files: int
    failed_files: int
    metadata: dict[str, object]
    warning: str | None


@dataclass(frozen=True)
class StagedImportOutcome:
    """Private detached disposition of one observed file."""

    filename: str | None
    status: Literal["pending", "noop", "failed"]
    counts: dict[str, Any] | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class StagedImportEvaluation:
    """One preview pass and its public aggregate summary."""

    outcomes: tuple[StagedImportOutcome, ...]
    summary: StagedImportSummary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def capture_staged_imports(import_dir: Path, *, fast: bool = False) -> StagedImportObservation:
    """Capture XLSX/selected JSON once; fast mode skips XLSX capture and all previews."""
    started = _now()
    directory_state = "present"
    try:
        paths = sorted(path for path in import_dir.iterdir() if path.suffix in {".xlsx", ".json"})
    except FileNotFoundError:
        paths = []
        directory_state = "absent"
    except OSError:
        raise StagedImportObservationError(
            "Staged import inventory could not be observed."
        ) from None
    captures: list[ExactWorkbookCapture] = []
    failures: list[StagedImportCaptureFailure] = []
    statements = tuple(
        capture
        for path in paths
        if path.suffix == ".json"
        if (capture := capture_statement(path)) is not None
    )
    paths = [path for path in paths if path.suffix == ".xlsx"]
    seen_files = len(paths) + len(statements)
    if not fast:
        for path in paths:
            try:
                captures.append(capture_exact_xlsx(path))
            except Exception:
                failures.append(StagedImportCaptureFailure(path.name))
    digests = tuple(
        sorted(
            {capture.digest_hex for capture in captures}
            | {capture.digest_hex for capture in statements}
        )
    )
    metadata: dict[str, object] = {
        "authority": "observed_staged_files",
        "directory_state": directory_state,
        "observation_started_at": started,
        "observation_completed_at": _now(),
        "preview_policy": "independent_baseline.v1",
        "capture_policy": "single_capture_bytes.v1",
        "fast": fast,
        "files_seen": seen_files,
        "files_examined": len(statements) if fast else seen_files,
        "files_not_examined": len(paths) if fast else 0,
        "files_captured": len(captures) + len(statements),
        "capture_failed_files": len(failures),
        "unique_digest_count": len(digests),
    }
    return StagedImportObservation(
        tuple(captures), digests, metadata, seen_files, len(failures), tuple(failures), statements
    )


def summarize_staged_imports(
    observation: StagedImportObservation, snapshot: ImportPreviewSnapshot
) -> StagedImportSummary:
    """Summarize independent per-file previews without reopening files or storage."""
    return evaluate_staged_imports(observation, snapshot).summary


def evaluate_staged_imports(
    observation: StagedImportObservation, snapshot: ImportPreviewSnapshot
) -> StagedImportEvaluation:
    """Preview captured files once and retain private per-file dispositions."""
    outcomes = [
        StagedImportOutcome(item.filename, "failed", failure_code=item.failure_code)
        for item in observation.capture_failures
    ]
    outcomes.extend(_preview_outcome(capture, snapshot) for capture in observation.captures)
    if not observation.metadata["fast"]:
        outcomes.extend(_statement_outcome(capture, snapshot) for capture in observation.statements)
    outcomes.sort(key=lambda item: item.filename or "")
    pending = (
        observation.seen_files
        if observation.metadata["fast"]
        else sum(item.status == "pending" for item in outcomes)
    )
    # Older positional observations retain aggregate failures without invented names.
    missing_failures = max(0, observation.capture_failed_files - len(observation.capture_failures))
    failed = missing_failures + sum(item.status == "failed" for item in outcomes)
    reused = sum(item.status == "noop" for item in outcomes)
    codes: Counter[str] = Counter(
        item.failure_code for item in outcomes if item.failure_code is not None
    )
    if missing_failures:
        codes["capture_failed"] += missing_failures
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
        warning = "Staged import previews were not evaluated in fast mode."
    summary = StagedImportSummary(pending, failed, metadata, warning)
    return StagedImportEvaluation(tuple(outcomes), summary)


def _preview_outcome(
    capture: ExactWorkbookCapture, snapshot: ImportPreviewSnapshot
) -> StagedImportOutcome:
    try:
        result = preview_captured_import(ExactImportCommand(capture, preview=True), snapshot).result
    except MutationValidationError:
        # Invalid/absent canonical lookup evidence must fail the entire bundle.
        raise
    except MutationConflictError:
        return StagedImportOutcome(
            capture.filename, "failed", failure_code="interpretation_conflict"
        )
    except Exception:
        return StagedImportOutcome(capture.filename, "failed", failure_code="mapping_failed")
    counts = result.get("counts")
    return StagedImportOutcome(
        capture.filename,
        "noop" if result.get("noop") is True else "pending",
        deepcopy(counts) if isinstance(counts, dict) else None,
    )


def _statement_outcome(
    capture: StatementCapture, snapshot: ImportPreviewSnapshot
) -> StagedImportOutcome:
    result = snapshot.statement_results.get(capture.digest_hex)
    if result is None:
        raise MutationValidationError("Statement digest was not requested in this snapshot.")
    if failure := result.get("failure_code"):
        return StagedImportOutcome(capture.filename, "failed", failure_code=str(failure))
    counts = deepcopy(result["counts"])
    empty = {"inserted": 0, "reused": 0, "quarantined": 0, "unsupported": 0}
    counts.update(
        transactions={
            **empty,
            "inserted": counts["created"],
            "reused": counts["reused"] + counts["linked"],
        },
        assets=dict(empty),
        overview=dict(empty),
        unknown_sheets=0,
        uncovered_rows=0,
    )
    return StagedImportOutcome(
        capture.filename, "noop" if result.get("noop") is True else "pending", counts
    )
