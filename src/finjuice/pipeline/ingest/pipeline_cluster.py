"""Single-file write-path helpers for the ingest pipeline.

Owns import-history recording, optional source archival, and the
transaction/asset/overview write-log-return path used by
:func:`ingest_file_detailed`. Public ingest entry points stay in
:mod:`finjuice.pipeline.ingest.pipeline`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl

from ..metadata.import_history import archive_source_file, record_import
from ..storage import csv_partition
from ._asset_processor import ingest_asset_snapshots
from ._overview_io import (
    _overview_has_writes,
    _write_banksalad_overview,
)
from ._transaction_processor import _build_transaction_dataframe

logger = logging.getLogger(__name__)


def _record_ingest_import(
    file_path: Path,
    csv_base_dir: Path,
    archive: bool,
    source_rows: int,
    file_mtime: str,
) -> str:
    """Record import history and optionally archive the source workbook.

    Returns:
        file_id issued (or reused) by import_history.
    """
    metadata_dir = csv_base_dir.parent / "metadata"

    file_id = record_import(
        metadata_dir=metadata_dir,
        file_path=file_path,
        file_mtime=file_mtime,
        source_rows=source_rows,
        archived=False,
    )

    if archive:
        archive_dir = metadata_dir / "archives"
        archived_path = archive_source_file(file_path, archive_dir, file_id)
        logger.info("Archived source file")

        record_import(
            metadata_dir=metadata_dir,
            file_path=file_path,
            file_mtime=file_mtime,
            source_rows=source_rows,
            archived=True,
            archived_path=archived_path,
        )

    return file_id


def _write_ingest_file_result(
    file_path: Path,
    csv_base_dir: Path,
    file_id: str,
    file_mtime: str,
    df: pl.DataFrame,
) -> dict[str, Any]:
    """Write transactions, asset snapshots, and overview for one loaded file."""
    df_transactions, skipped_rows = _build_transaction_dataframe(file_path, df, file_id)

    result = csv_partition.append_transactions(
        csv_base_dir,
        df_transactions,
        deduplicate=True,
    )

    inserted = result["rows_inserted"]
    skipped_dedup = result["rows_skipped"]  # Skipped due to deduplication

    asset_inserted, asset_skipped, asset_warnings = ingest_asset_snapshots(
        file_path=file_path,
        csv_base_dir=csv_base_dir,
        file_id=file_id,
        file_mtime=file_mtime,
    )
    for warning in asset_warnings:
        logger.warning(warning)
    if asset_inserted > 0 or asset_skipped > 0:
        logger.info(
            "Asset snapshot ingestion complete: "
            f"{asset_inserted} inserted, {asset_skipped} duplicates skipped"
        )

    overview_summary = _write_banksalad_overview(
        file_path=file_path,
        csv_base_dir=csv_base_dir,
        file_id=file_id,
        file_mtime=file_mtime,
    )
    if _overview_has_writes(overview_summary):
        logger.info("Banksalad overview ingestion complete")
    for warning in overview_summary["warnings"]:
        logger.warning("Banksalad overview warning: %s", warning)

    logger.info(
        f"Ingestion complete (Polars): {inserted} inserted, "
        f"{skipped_dedup} duplicates skipped, {len(skipped_rows)} rows skipped (validation)"
    )

    return {
        "transactions": {
            "inserted": int(inserted),
            "dedup_skips": int(skipped_dedup),
            "validation_skips": len(skipped_rows),
            "skipped_rows": skipped_rows,
        },
        "asset_snapshots": {
            "inserted": int(asset_inserted),
            "dedup_skips": int(asset_skipped),
            "warnings": asset_warnings,
        },
        "banksalad_overview": overview_summary,
    }
