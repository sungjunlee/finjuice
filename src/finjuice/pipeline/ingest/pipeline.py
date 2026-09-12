"""
XLSX Ingestion Pipeline for Banksalad exports (Polars-only).

Provides end-to-end ingestion pipeline that reads Banksalad XLSX files,
maps columns, calculates row hashes for deduplication, and writes to CSV partitions.

Public API: preview_ingest_paths, preview_ingest_all_files, ingest_file,
ingest_paths, ingest_all_files

Write-path summary helpers live in
:mod:`finjuice.pipeline.ingest.pipeline_helpers`. Single-file import
recording and partition writes live in
:mod:`finjuice.pipeline.ingest.pipeline_cluster`. Both are re-exported here
so existing callers can keep importing from this module.
"""

import logging
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import polars as pl

from ..metadata.import_history_helpers import list_unprocessed_xlsx
from ..validation import ValidationError
from ._preview import (
    _accumulate_preview_file,
    _build_preview_context,
    _empty_preview_ingest_summary,
    _finalize_preview_ingest_summary,
    _preview_ingest_path,
    _PreviewTotals,
)
from ._transaction_processor import _load_transaction_source
from .pipeline_cluster import (
    _record_ingest_import,
    _write_ingest_file_result,
)
from .pipeline_helpers import (
    _accumulate_ingest_file,
    _empty_ingest_all_summary,
    _empty_ingest_file_summary,  # noqa: F401 — re-exported for existing pipeline imports
    _finalize_ingest_all_summary,
    _IngestTotals,
)

logger = logging.getLogger(__name__)


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
        return _empty_preview_ingest_summary(archive)

    context = _build_preview_context(csv_base_dir, archive)
    totals = _PreviewTotals()
    failed_files: list[tuple[str, str]] = []

    total = len(file_paths)
    for index, file_path in enumerate(file_paths, start=1):
        logger.info("Previewing file %s/%s: %s", index, total, file_path.name)
        try:
            _accumulate_preview_file(totals, _preview_ingest_path(file_path, context))
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

    return _finalize_preview_ingest_summary(file_paths, archive, totals, failed_files)


def preview_ingest_all_files(
    import_dir: Path,
    csv_base_dir: Path,
    archive: bool = False,
    *,
    skip_processed: bool = False,
    metadata_dir: Path | None = None,
) -> dict[str, Any]:
    """Preview batch ingest for XLSX files in the import directory.

    When ``skip_processed`` is true, workbooks whose basename is already in
    import history are not opened. ``files_found`` stays the staged glob
    count; ``history_skipped`` / ``would_parse`` report the filter.
    """
    staged = list(import_dir.glob("*.xlsx"))
    selected = staged
    skipped = 0
    if skip_processed:
        history_dir = metadata_dir or (csv_base_dir.parent / "metadata")
        selected = list_unprocessed_xlsx(import_dir, history_dir)
        skipped = len(staged) - len(selected)

    preview = preview_ingest_paths(selected, csv_base_dir, archive=archive)
    preview["files_found"] = len(staged)
    preview["history_skipped"] = skipped
    preview["would_parse"] = len(selected)
    return preview


def ingest_file(
    file_path: Path, csv_base_dir: Path, archive: bool = False
) -> tuple[int, int, list[str]]:
    """Ingest a single XLSX file and return the legacy transaction tuple."""
    result = ingest_file_detailed(file_path, csv_base_dir, archive=archive)
    transactions = result["transactions"]
    return (
        int(transactions["inserted"]),
        int(transactions["dedup_skips"]),
        list(transactions["skipped_rows"]),
    )


def ingest_file_detailed(
    file_path: Path, csv_base_dir: Path, archive: bool = False
) -> dict[str, Any]:
    """
    Ingest a single XLSX file into CSV partitions with detailed summaries.

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

    Raises:
        ValidationError: If required columns are missing from file
    """
    df, source_rows, file_mtime = _load_transaction_source(file_path)
    file_id = _record_ingest_import(file_path, csv_base_dir, archive, source_rows, file_mtime)
    return _write_ingest_file_result(file_path, csv_base_dir, file_id, file_mtime, df)


def ingest_paths(
    file_paths: list[Path],
    csv_base_dir: Path,
    archive: bool = False,
) -> dict[str, Any]:
    """Batch ingest an explicit list of XLSX workbooks.

    Unlike :func:`ingest_all_files`, this does not glob ``imports/``. An empty
    list ingests nothing. Failed files are logged and skipped so remaining
    paths still run.

    Args:
        file_paths: Workbooks to ingest, in order.
        csv_base_dir: Base directory for CSV partitions.
        archive: If True, copy source files to metadata/archives/.

    Returns:
        dict: Summary with ``files``, ``inserted``, ``updated``, ``failed``,
        and ``failed_files``.
    """
    if not file_paths:
        return _empty_ingest_all_summary()

    logger.info("Ingesting %s explicit XLSX file(s)", len(file_paths))

    totals = _IngestTotals()
    failed_files: list[tuple[str, str]] = []
    total = len(file_paths)

    for index, file_path in enumerate(file_paths, start=1):
        logger.info("Ingesting file %s/%s: %s", index, total, file_path.name)
        try:
            _accumulate_ingest_file(
                totals, ingest_file_detailed(file_path, csv_base_dir, archive=archive)
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
            logger.warning("Ingestion cancelled by user")
            failed_files.append((file_path.name, "Cancelled by user"))
            break
        except (OSError, pl.exceptions.PolarsError, BadZipFile) as e:
            logger.error("Unexpected error processing source workbook (%s)", type(e).__name__)
            failed_files.append((file_path.name, f"Unexpected error: {type(e).__name__}: {str(e)}"))

    summary = _finalize_ingest_all_summary(file_paths, totals, failed_files)
    logger.info(
        f"Ingestion summary: {summary['files']} files, "
        f"{summary['inserted']} inserted, {summary['updated']} updated, "
        f"{summary['failed']} failed"
    )
    return summary


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
        return _empty_ingest_all_summary()

    logger.info(f"Found {len(xlsx_files)} XLSX file(s)")
    return ingest_paths(xlsx_files, csv_base_dir, archive=archive)
