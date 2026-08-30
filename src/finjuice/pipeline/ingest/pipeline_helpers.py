"""Write-path summary helpers for the ingest pipeline.

Owns per-file and batch ingest write summaries. Public ingest entry points
stay in :mod:`finjuice.pipeline.ingest.pipeline`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._overview_io import (
    _empty_overview_write_summary,
    _merge_overview_write_totals,
)


@dataclass
class _IngestTotals:
    """Running totals for a batch ``ingest_all_files`` run."""

    inserted: int = 0
    updated: int = 0
    overview: dict[str, Any] = field(default_factory=_empty_overview_write_summary)


def _empty_ingest_file_summary() -> dict[str, Any]:
    """Return the zeroed per-file write summary payload."""
    return {
        "transactions": {
            "inserted": 0,
            "dedup_skips": 0,
            "validation_skips": 0,
            "skipped_rows": [],
        },
        "asset_snapshots": {"inserted": 0, "dedup_skips": 0, "warnings": []},
        "banksalad_overview": _empty_overview_write_summary(),
    }


def _empty_ingest_all_summary() -> dict[str, Any]:
    """Return the batch payload used when no source files are found."""
    return {"files": 0, "inserted": 0, "updated": 0, "failed": 0}


def _accumulate_ingest_file(totals: _IngestTotals, result: dict[str, Any]) -> None:
    """Fold one file's write summary into the batch totals."""
    totals.inserted += int(result["transactions"]["inserted"])
    totals.updated += int(result["transactions"]["dedup_skips"])
    _merge_overview_write_totals(totals.overview, result["banksalad_overview"])


def _finalize_ingest_all_summary(
    xlsx_files: list[Path],
    totals: _IngestTotals,
    failed_files: list[tuple[str, str]],
) -> dict[str, Any]:
    """Build the public batch ingest payload from accumulated write totals."""
    return {
        "files": len(xlsx_files),
        "inserted": totals.inserted,
        "updated": totals.updated,
        "banksalad_overview": totals.overview,
        "failed": len(failed_files),
        "failed_files": failed_files,
    }
