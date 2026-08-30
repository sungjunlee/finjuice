"""Dry-run preview helpers for the ingest pipeline.

Public ingest entry points stay in ``pipeline.py``. This module owns preview
context, per-file preview, and aggregate preview summaries.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._asset_processor import _build_asset_snapshot_dataframe
from ._overview_io import (
    _banksalad_overview_base_dir,
    _empty_overview_preview_summary,
    _merge_overview_preview_totals,
    _OverviewPreviewCaches,
    _OverviewPreviewFrames,
    _preview_banksalad_overview,
    _sorted_overview_summary,
)
from ._overview_processor import parse_banksalad_overview
from ._partition_preview import (
    _preview_append_asset_snapshots,
    _preview_append_transactions,
)
from ._transaction_processor import (
    _build_transaction_dataframe,
    _load_transaction_source,
)

_PREVIEW_FILE_ID = "dry_run_preview"


@dataclass
class _PreviewContext:
    csv_base_dir: Path
    asset_base_dir: Path
    banksalad_base_dir: Path
    archive: bool
    transaction_cache: dict[tuple[int, int], set[str]]
    asset_cache: dict[tuple[int, int], set[tuple[str, str, str]]]
    overview_caches: _OverviewPreviewCaches


@dataclass
class _PreviewTotals:
    tx_inserted: int = 0
    tx_skipped: int = 0
    validation_skips: int = 0
    asset_inserted: int = 0
    asset_skipped: int = 0
    overview: dict[str, Any] = field(default_factory=_empty_overview_preview_summary)
    tx_partitions: set[str] = field(default_factory=set)
    asset_partitions: set[str] = field(default_factory=set)
    asset_warnings: list[str] = field(default_factory=list)
    file_summaries: list[dict[str, Any]] = field(default_factory=list)


def _empty_preview_ingest_summary(archive: bool) -> dict[str, Any]:
    """Return the dry-run payload used when no source files are supplied."""
    return _finalize_preview_ingest_summary(
        file_paths=[],
        archive=archive,
        totals=_PreviewTotals(),
        failed_files=[],
    )


def _build_preview_context(csv_base_dir: Path, archive: bool) -> _PreviewContext:
    return _PreviewContext(
        csv_base_dir=csv_base_dir,
        asset_base_dir=csv_base_dir.parent / "assets" / "snapshots",
        banksalad_base_dir=_banksalad_overview_base_dir(csv_base_dir),
        archive=archive,
        transaction_cache={},
        asset_cache={},
        overview_caches=_OverviewPreviewCaches(
            overview_facts={},
            balance={},
            cashflow={},
            insurance={},
            investments={},
            loans={},
        ),
    )


def _preview_ingest_path(file_path: Path, context: _PreviewContext) -> dict[str, Any]:
    df, source_rows, file_mtime = _load_transaction_source(file_path)
    tx_df, skipped_rows = _build_transaction_dataframe(file_path, df, _PREVIEW_FILE_ID)
    tx_preview = _preview_append_transactions(
        context.csv_base_dir,
        tx_df,
        context.transaction_cache,
    )
    asset_df, asset_warnings = _build_asset_snapshot_dataframe(
        file_path=file_path,
        file_id=_PREVIEW_FILE_ID,
        file_mtime=file_mtime,
    )
    asset_preview = _preview_append_asset_snapshots(
        context.asset_base_dir,
        asset_df,
        context.asset_cache,
    )
    overview_parse = parse_banksalad_overview(
        file_path=file_path,
        file_id=_PREVIEW_FILE_ID,
        file_mtime=file_mtime,
    )
    overview_preview = _preview_banksalad_overview(
        context.banksalad_base_dir,
        context.overview_caches,
        _OverviewPreviewFrames(
            overview_facts=overview_parse.overview_facts,
            balance=overview_parse.balance,
            cashflow=overview_parse.cashflow,
            insurance=overview_parse.insurance,
            investments=overview_parse.investments,
            loans=overview_parse.loans,
            warnings=overview_parse.warnings,
        ),
    )

    return {
        "source_file": str(file_path),
        "source_rows": source_rows,
        "would_archive": context.archive,
        "transactions": {
            "estimated_new_rows": int(tx_preview["rows_inserted"]),
            "estimated_dedup_skips": int(tx_preview["rows_skipped"]),
            "validation_skips": len(skipped_rows),
            "affected_partitions": tx_preview["affected_partitions"],
        },
        "asset_snapshots": {
            "estimated_new_rows": int(asset_preview["rows_inserted"]),
            "estimated_dedup_skips": int(asset_preview["rows_skipped"]),
            "affected_partitions": asset_preview["affected_partitions"],
            "warnings": asset_warnings,
        },
        "banksalad_overview": overview_preview,
    }


def _accumulate_preview_file(totals: _PreviewTotals, file_summary: dict[str, Any]) -> None:
    """Fold one file preview into the batch totals."""
    transactions = file_summary["transactions"]
    assets = file_summary["asset_snapshots"]
    overview_preview = file_summary["banksalad_overview"]

    totals.tx_inserted += int(transactions["estimated_new_rows"])
    totals.tx_skipped += int(transactions["estimated_dedup_skips"])
    totals.validation_skips += int(transactions["validation_skips"])
    totals.asset_inserted += int(assets["estimated_new_rows"])
    totals.asset_skipped += int(assets["estimated_dedup_skips"])
    _merge_overview_preview_totals(totals.overview, overview_preview)
    totals.tx_partitions.update(str(path) for path in transactions["affected_partitions"])
    totals.asset_partitions.update(str(path) for path in assets["affected_partitions"])
    totals.asset_warnings.extend(assets["warnings"])
    totals.file_summaries.append(file_summary)


def _finalize_preview_ingest_summary(
    file_paths: list[Path],
    archive: bool,
    totals: _PreviewTotals,
    failed_files: list[tuple[str, str]],
) -> dict[str, Any]:
    """Build the public dry-run payload from accumulated preview totals."""
    return {
        "files_found": len(file_paths),
        "archive_requested": archive,
        "transactions": {
            "estimated_new_rows": totals.tx_inserted,
            "estimated_dedup_skips": totals.tx_skipped,
            "validation_skips": totals.validation_skips,
            "affected_partitions": sorted(totals.tx_partitions),
        },
        "asset_snapshots": {
            "estimated_new_rows": totals.asset_inserted,
            "estimated_dedup_skips": totals.asset_skipped,
            "affected_partitions": sorted(totals.asset_partitions),
            "warnings": totals.asset_warnings,
        },
        "banksalad_overview": _sorted_overview_summary(totals.overview),
        "failed": len(failed_files),
        "failed_files": failed_files,
        "files": totals.file_summaries,
    }
