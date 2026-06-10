"""
XLSX Ingestion Pipeline for Banksalad exports (Polars-only).

Provides end-to-end ingestion pipeline that reads Banksalad XLSX files,
maps columns, calculates row hashes for deduplication, and writes to CSV partitions.

Public API: preview_ingest_paths, preview_ingest_all_files, ingest_file, ingest_all_files
"""

import logging
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import polars as pl

from ..metadata.import_history import archive_source_file, record_import
from ..storage import csv_partition
from ..validation import ValidationError
from ._asset_processor import _build_asset_snapshot_dataframe, ingest_asset_snapshots
from ._partition_preview import (
    _preview_append_asset_snapshots,
    _preview_append_transactions,
)
from ._transaction_processor import (
    _build_transaction_dataframe,
    _load_transaction_source,
)

logger = logging.getLogger(__name__)

_PREVIEW_FILE_ID = "dry_run_preview"


def preview_ingest_paths(
    file_paths: list[Path],
    csv_base_dir: Path,
    archive: bool = False,
) -> dict[str, Any]:
    """
    Preview ingest results for one or more XLSX files without writing any files.

    Simulates the same partitioning and deduplication rules as the write path.
    """
    if not file_paths:
        return {
            "files_found": 0,
            "archive_requested": archive,
            "transactions": {
                "estimated_new_rows": 0,
                "estimated_dedup_skips": 0,
                "validation_skips": 0,
                "affected_partitions": [],
            },
            "asset_snapshots": {
                "estimated_new_rows": 0,
                "estimated_dedup_skips": 0,
                "affected_partitions": [],
                "warnings": [],
            },
            "failed": 0,
            "failed_files": [],
            "files": [],
        }

    asset_base_dir = csv_base_dir.parent / "assets" / "snapshots"
    transaction_cache: dict[tuple[int, int], set[str]] = {}
    asset_cache: dict[tuple[int, int], set[tuple[str, str, str]]] = {}
    file_summaries: list[dict[str, Any]] = []
    failed_files: list[tuple[str, str]] = []
    total_tx_inserted = 0
    total_tx_skipped = 0
    total_validation_skips = 0
    total_asset_inserted = 0
    total_asset_skipped = 0
    all_tx_partitions: set[str] = set()
    all_asset_partitions: set[str] = set()
    all_asset_warnings: list[str] = []

    for file_path in file_paths:
        try:
            df, source_rows, file_mtime = _load_transaction_source(file_path)
            tx_df, skipped_rows = _build_transaction_dataframe(file_path, df, _PREVIEW_FILE_ID)
            tx_preview = _preview_append_transactions(csv_base_dir, tx_df, transaction_cache)
            asset_df, asset_warnings = _build_asset_snapshot_dataframe(
                file_path=file_path,
                file_id=_PREVIEW_FILE_ID,
                file_mtime=file_mtime,
            )
            asset_preview = _preview_append_asset_snapshots(asset_base_dir, asset_df, asset_cache)

            total_tx_inserted += int(tx_preview["rows_inserted"])
            total_tx_skipped += int(tx_preview["rows_skipped"])
            total_validation_skips += len(skipped_rows)
            total_asset_inserted += int(asset_preview["rows_inserted"])
            total_asset_skipped += int(asset_preview["rows_skipped"])
            all_tx_partitions.update(str(path) for path in tx_preview["affected_partitions"])
            all_asset_partitions.update(str(path) for path in asset_preview["affected_partitions"])
            all_asset_warnings.extend(asset_warnings)

            file_summaries.append(
                {
                    "source_file": str(file_path),
                    "source_rows": source_rows,
                    "would_archive": archive,
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
                }
            )
        except (FileNotFoundError, PermissionError) as e:
            logger.error("Cannot access source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"File access error: {str(e)}"))
        except ValidationError as e:
            logger.error("Schema validation failed for source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Schema validation error: {str(e)}"))
        except (ValueError, KeyError) as e:
            logger.error("Invalid data in source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Data validation error: {str(e)}"))
        except pl.exceptions.ComputeError as e:
            logger.error("Cannot parse source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Parse error: {str(e)}"))
        except KeyboardInterrupt:
            logger.warning("Ingestion preview cancelled by user")
            failed_files.append((file_path.name, "Cancelled by user"))
            break
        except (OSError, pl.exceptions.PolarsError, BadZipFile) as e:
            logger.error("Unexpected error previewing source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Unexpected error: {type(e).__name__}: {str(e)}"))

    return {
        "files_found": len(file_paths),
        "archive_requested": archive,
        "transactions": {
            "estimated_new_rows": total_tx_inserted,
            "estimated_dedup_skips": total_tx_skipped,
            "validation_skips": total_validation_skips,
            "affected_partitions": sorted(all_tx_partitions),
        },
        "asset_snapshots": {
            "estimated_new_rows": total_asset_inserted,
            "estimated_dedup_skips": total_asset_skipped,
            "affected_partitions": sorted(all_asset_partitions),
            "warnings": all_asset_warnings,
        },
        "failed": len(failed_files),
        "failed_files": failed_files,
        "files": file_summaries,
    }


def preview_ingest_all_files(
    import_dir: Path, csv_base_dir: Path, archive: bool = False
) -> dict[str, Any]:
    """Preview batch ingest for all XLSX files in the import directory."""
    return preview_ingest_paths(list(import_dir.glob("*.xlsx")), csv_base_dir, archive=archive)


def ingest_file(
    file_path: Path, csv_base_dir: Path, archive: bool = False
) -> tuple[int, int, list[str]]:
    """
    Ingest a single XLSX file into CSV partitions (Polars-only).

    The function performs the following steps:
    1. Read XLSX file with Polars
    2. Map columns to standard names using schema detection
    3. (Optional) Archive source file to metadata/archives/ if archive=True
    4. Record import in import_history.csv
    5. For each row:
       - Calculate row_hash for deduplication
       - Build datetime field from date + time
       - Normalize amount based on transaction type
       - Build transaction dict with all fields
    6. Group transactions by year/month
    7. For each partition:
       - Load existing CSV partition
       - Merge with new transactions (deduplicate by row_hash)
       - Write back atomically

    Args:
        file_path: Path to XLSX file to ingest
        csv_base_dir: Base directory for CSV partitions (e.g., data/transactions/)
        archive: If True, copy source file to metadata/archives/ for reproducibility
            (default: False)

    Returns:
        Tuple of (inserted_count, updated_count, skipped_rows_list)

    Raises:
        ValidationError: If required columns are missing from file
    """
    df, source_rows, file_mtime = _load_transaction_source(file_path)

    if source_rows == 0:
        return 0, 0, []

    # Set up metadata tracking
    metadata_dir = csv_base_dir.parent / "metadata"

    # Record import first to get real file_id
    file_id = record_import(
        metadata_dir=metadata_dir,
        file_path=file_path,
        file_mtime=file_mtime,
        source_rows=source_rows,
        archived=False,
    )

    # Optionally archive source file
    if archive:
        archive_dir = metadata_dir / "archives"
        archived_path = archive_source_file(file_path, archive_dir, file_id)
        logger.info("Archived source file")

        # Update import history with archive info
        record_import(
            metadata_dir=metadata_dir,
            file_path=file_path,
            file_mtime=file_mtime,
            source_rows=source_rows,
            archived=True,
            archived_path=archived_path,
        )

    df_transactions, skipped_rows = _build_transaction_dataframe(file_path, df, file_id)

    # Write to CSV partitions (with deduplication)
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

    logger.info(
        f"Ingestion complete (Polars): {inserted} inserted, "
        f"{skipped_dedup} duplicates skipped, {len(skipped_rows)} rows skipped (validation)"
    )

    return inserted, skipped_dedup, skipped_rows


def ingest_all_files(import_dir: Path, csv_base_dir: Path, archive: bool = False) -> dict[str, Any]:
    """
    Batch ingest all XLSX files from import directory.

    Globs for all *.xlsx files in the directory and ingests each one sequentially.
    If a file fails to ingest, the error is logged and processing continues
    with the next file.

    Args:
        import_dir: Directory containing XLSX files to ingest
        csv_base_dir: Base directory for CSV partitions
        archive: If True, copy source files to metadata/archives/ (default: False)

    Returns:
        dict: Summary with keys:
            - 'files': Total number of XLSX files found
            - 'inserted': Total number of new transactions inserted
            - 'updated': Total number of existing transactions updated
            - 'failed': Number of files that failed to ingest
            - 'failed_files': List of (filename, error_message) tuples

    Example:
        >>> summary = ingest_all_files(Path('imports/'), Path('data/transactions'))
        >>> print(f"Processed {summary['files']} files, "
        ...       f"{summary['inserted']} new transactions")
    """
    xlsx_files = list(import_dir.glob("*.xlsx"))

    if not xlsx_files:
        logger.warning(f"No XLSX files found in {import_dir}")
        return {"files": 0, "inserted": 0, "updated": 0, "failed": 0}

    logger.info(f"Found {len(xlsx_files)} XLSX file(s)")

    total_inserted = 0
    total_updated = 0
    failed_files = []

    for file_path in xlsx_files:
        try:
            inserted, updated, skipped = ingest_file(file_path, csv_base_dir, archive=archive)
            total_inserted += inserted
            total_updated += updated
        except (FileNotFoundError, PermissionError) as e:
            # File access errors - expected during file processing
            logger.error("Cannot access source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"File access error: {str(e)}"))
        except ValidationError as e:
            # Schema validation errors - provide user-friendly message
            logger.error("Schema validation failed for source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Schema validation error: {str(e)}"))
        except (ValueError, KeyError) as e:
            # Data validation errors - expected from malformed files
            logger.error("Invalid data in source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Data validation error: {str(e)}"))
        except pl.exceptions.ComputeError as e:
            # Polars parsing errors - expected from corrupted Excel files
            logger.error("Cannot parse source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Parse error: {str(e)}"))
        except KeyboardInterrupt:
            # User cancellation - clean exit
            logger.warning("Ingestion cancelled by user")
            failed_files.append((file_path.name, "Cancelled by user"))
            break
        except (OSError, pl.exceptions.PolarsError, BadZipFile) as e:
            # Unexpected errors - log full stack trace and continue
            logger.error("Unexpected error processing source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Unexpected error: {type(e).__name__}: {str(e)}"))
            # Continue processing remaining files despite unexpected errors

    # Build summary report
    summary = {
        "files": len(xlsx_files),
        "inserted": total_inserted,
        "updated": total_updated,
        "failed": len(failed_files),
        "failed_files": failed_files,
    }

    logger.info(
        f"Ingestion summary: {summary['files']} files, "
        f"{summary['inserted']} inserted, {summary['updated']} updated, "
        f"{summary['failed']} failed"
    )

    return summary
