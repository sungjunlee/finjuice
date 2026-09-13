"""Project independent staged previews without inventing legacy skip counts."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.automation_pending_imports import (
    PendingImportFailure,
    PendingImportFile,
    PendingImportsSignal,
)
from finjuice.pipeline.checkup.import_preview import StagedImportEvaluation


def pending_from_evaluation(
    evaluation: StagedImportEvaluation, sample_limit: int
) -> tuple[PendingImportsSignal, dict[str, Any]]:
    """Return independent estimates and separate canonical disposition totals."""
    totals: dict[str, Any] = {
        family: dict.fromkeys(("inserted", "reused", "quarantined", "unsupported"), 0)
        for family in ("transactions", "assets", "overview")
    }
    totals.update(unknown_sheets=0, uncovered_rows=0)
    failures: list[PendingImportFailure] = []
    samples: list[PendingImportFile] = []
    for outcome in evaluation.outcomes:
        if outcome.status == "failed":
            failures.append(
                PendingImportFailure(outcome.filename, outcome.failure_code or "preview_failed")
            )
        elif outcome.status == "pending":
            counts = outcome.counts
            if counts is None:
                raise ValueError("Canonical preview counts are unavailable.")
            _accumulate_counts(totals, counts)
            if len(samples) < sample_limit:
                samples.append(
                    PendingImportFile(
                        outcome.filename,
                        counts["transactions"]["inserted"],
                        counts["assets"]["inserted"],
                        None,
                    )
                )
    summary = evaluation.summary
    if len(failures) != summary.failed_files:
        raise ValueError("Canonical preview failures are incomplete.")
    return (
        PendingImportsSignal(
            status="present" if summary.pending_files or failures else "clear",
            files_found=_count(summary.metadata["files_seen"]),
            pending_files=summary.pending_files,
            estimated_new_rows=totals["transactions"]["inserted"],
            estimated_new_asset_rows=totals["assets"]["inserted"],
            failed_files=failures,
            sample_files=samples,
        ),
        totals,
    )


def _accumulate_counts(totals: dict[str, Any], counts: dict[str, Any]) -> None:
    for name, aggregate in totals.items():
        if isinstance(aggregate, dict):
            for disposition in aggregate:
                aggregate[disposition] += _count(counts[name][disposition])
        else:
            totals[name] += _count(counts[name])


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Canonical preview counts must be nonnegative integers.")
    return value
