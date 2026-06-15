"""
XLSX Ingestion Pipeline for Banksalad exports (Polars-only).

Provides end-to-end ingestion pipeline that reads Banksalad XLSX files,
maps columns, calculates row hashes for deduplication, and writes to CSV partitions.

Public API: preview_ingest_paths, preview_ingest_all_files, ingest_file, ingest_all_files
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import polars as pl

from ..metadata.import_history import archive_source_file, record_import
from ..storage import csv_partition
from ..validation import ValidationError
from ._asset_processor import _build_asset_snapshot_dataframe, ingest_asset_snapshots
from ._overview_processor import parse_banksalad_overview
from ._partition_preview import (
    _OverviewPreviewSpec,
    _preview_append_asset_snapshots,
    _preview_append_banksalad_cashflow,
    _preview_append_banksalad_overview_table,
    _preview_append_transactions,
)
from ._transaction_processor import (
    _build_transaction_dataframe,
    _load_transaction_source,
)

logger = logging.getLogger(__name__)

_PREVIEW_FILE_ID = "dry_run_preview"
_OVERVIEW_TABLE_NAMES = ("overview_facts", "balance", "cashflow")


@dataclass
class _OverviewPreviewCaches:
    overview_facts: dict[tuple[int, int], set[tuple[object, ...]]]
    balance: dict[tuple[int, int], set[tuple[object, ...]]]
    cashflow: dict[tuple[int, int], set[tuple[object, ...]]]


@dataclass
class _PreviewContext:
    csv_base_dir: Path
    asset_base_dir: Path
    banksalad_base_dir: Path
    archive: bool
    transaction_cache: dict[tuple[int, int], set[str]]
    asset_cache: dict[tuple[int, int], set[tuple[str, str, str]]]
    overview_caches: _OverviewPreviewCaches


@dataclass(frozen=True)
class _OverviewPreviewFrames:
    overview_facts: pl.DataFrame
    balance: pl.DataFrame
    cashflow: pl.DataFrame
    warnings: list[str]


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
            "banksalad_overview": _empty_overview_preview_summary(),
            "failed": 0,
            "failed_files": [],
            "files": [],
        }

    context = _build_preview_context(csv_base_dir, archive)
    file_summaries: list[dict[str, Any]] = []
    failed_files: list[tuple[str, str]] = []
    total_tx_inserted = 0
    total_tx_skipped = 0
    total_validation_skips = 0
    total_asset_inserted = 0
    total_asset_skipped = 0
    overview_totals = _empty_overview_preview_summary()
    all_tx_partitions: set[str] = set()
    all_asset_partitions: set[str] = set()
    all_asset_warnings: list[str] = []

    for file_path in file_paths:
        try:
            file_summary = _preview_ingest_path(file_path, context)
            transactions = file_summary["transactions"]
            assets = file_summary["asset_snapshots"]
            overview_preview = file_summary["banksalad_overview"]

            total_tx_inserted += int(transactions["estimated_new_rows"])
            total_tx_skipped += int(transactions["estimated_dedup_skips"])
            total_validation_skips += int(transactions["validation_skips"])
            total_asset_inserted += int(assets["estimated_new_rows"])
            total_asset_skipped += int(assets["estimated_dedup_skips"])
            _merge_overview_preview_totals(overview_totals, overview_preview)
            all_tx_partitions.update(str(path) for path in transactions["affected_partitions"])
            all_asset_partitions.update(str(path) for path in assets["affected_partitions"])
            all_asset_warnings.extend(assets["warnings"])
            file_summaries.append(file_summary)
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
        "banksalad_overview": _sorted_overview_summary(overview_totals),
        "failed": len(failed_files),
        "failed_files": failed_files,
        "files": file_summaries,
    }


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


def preview_ingest_all_files(
    import_dir: Path, csv_base_dir: Path, archive: bool = False
) -> dict[str, Any]:
    """Preview batch ingest for all XLSX files in the import directory."""
    return preview_ingest_paths(list(import_dir.glob("*.xlsx")), csv_base_dir, archive=archive)


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
    overview_totals = _empty_overview_write_summary()
    failed_files = []

    for file_path in xlsx_files:
        try:
            result = ingest_file_detailed(file_path, csv_base_dir, archive=archive)
            total_inserted += int(result["transactions"]["inserted"])
            total_updated += int(result["transactions"]["dedup_skips"])
            _merge_overview_write_totals(overview_totals, result["banksalad_overview"])
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
        "banksalad_overview": overview_totals,
        "failed": len(failed_files),
        "failed_files": failed_files,
    }

    logger.info(
        f"Ingestion summary: {summary['files']} files, "
        f"{summary['inserted']} inserted, {summary['updated']} updated, "
        f"{summary['failed']} failed"
    )

    return summary


def _banksalad_overview_base_dir(csv_base_dir: Path) -> Path:
    return csv_base_dir.parent / "banksalad"


def _empty_ingest_file_summary() -> dict[str, Any]:
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


def _empty_overview_preview_summary() -> dict[str, Any]:
    return {
        table_name: {
            "estimated_new_rows": 0,
            "estimated_dedup_skips": 0,
            "affected_partitions": [],
        }
        for table_name in _OVERVIEW_TABLE_NAMES
    } | {"warnings": []}


def _empty_overview_write_summary() -> dict[str, Any]:
    return {
        table_name: {
            "inserted": 0,
            "dedup_skips": 0,
            "partitions_updated": 0,
        }
        for table_name in _OVERVIEW_TABLE_NAMES
    } | {"warnings": []}


def _preview_banksalad_overview(
    banksalad_base_dir: Path,
    caches: _OverviewPreviewCaches,
    frames: _OverviewPreviewFrames,
) -> dict[str, Any]:
    result = _empty_overview_preview_summary()
    result["overview_facts"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "overview_facts",
            frames.overview_facts,
            caches.overview_facts,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_overview_facts_month,
                path_builder=csv_partition.get_banksalad_overview_facts_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["balance"] = _preview_overview_table_result(
        _preview_append_banksalad_overview_table(
            banksalad_base_dir / "balance",
            frames.balance,
            caches.balance,
            _OverviewPreviewSpec(
                dedup_key=csv_partition.BANKSALAD_BALANCE_DEDUP_KEY,
                read_month=csv_partition.read_banksalad_balance_month,
                path_builder=csv_partition.get_banksalad_balance_partition_path,
                partition_column="snapshot_date",
            ),
        )
    )
    result["cashflow"] = _preview_overview_table_result(
        _preview_append_banksalad_cashflow(
            banksalad_base_dir / "cashflow",
            frames.cashflow,
            caches.cashflow,
        )
    )
    result["warnings"] = frames.warnings
    return result


def _write_banksalad_overview(
    file_path: Path,
    csv_base_dir: Path,
    file_id: str,
    file_mtime: str,
) -> dict[str, Any]:
    parsed = parse_banksalad_overview(file_path=file_path, file_id=file_id, file_mtime=file_mtime)
    banksalad_base_dir = _banksalad_overview_base_dir(csv_base_dir)
    result = _empty_overview_write_summary()

    result["overview_facts"] = _write_overview_table_result(
        csv_partition.append_banksalad_overview_facts(
            banksalad_base_dir / "overview_facts",
            parsed.overview_facts,
        )
    )
    result["balance"] = _write_overview_table_result(
        csv_partition.append_banksalad_balance(banksalad_base_dir / "balance", parsed.balance)
    )
    result["cashflow"] = _write_overview_table_result(
        csv_partition.append_banksalad_cashflow(banksalad_base_dir / "cashflow", parsed.cashflow)
    )
    result["warnings"] = parsed.warnings
    return result


def _write_overview_table_result(append_result: dict[str, Any]) -> dict[str, int]:
    return {
        "inserted": int(append_result["rows_inserted"]),
        "dedup_skips": int(append_result["rows_skipped"]),
        "partitions_updated": int(append_result["partitions_updated"]),
    }


def _preview_overview_table_result(preview_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "estimated_new_rows": int(preview_result["rows_inserted"]),
        "estimated_dedup_skips": int(preview_result["rows_skipped"]),
        "affected_partitions": preview_result["affected_partitions"],
    }


def _merge_overview_preview_totals(total: dict[str, Any], item: dict[str, Any]) -> None:
    for table_name in _OVERVIEW_TABLE_NAMES:
        total[table_name]["estimated_new_rows"] += int(item[table_name]["estimated_new_rows"])
        total[table_name]["estimated_dedup_skips"] += int(item[table_name]["estimated_dedup_skips"])
        total[table_name]["affected_partitions"].extend(item[table_name]["affected_partitions"])
    total["warnings"].extend(item["warnings"])


def _merge_overview_write_totals(total: dict[str, Any], item: dict[str, Any]) -> None:
    for table_name in _OVERVIEW_TABLE_NAMES:
        total[table_name]["inserted"] += int(item[table_name]["inserted"])
        total[table_name]["dedup_skips"] += int(item[table_name]["dedup_skips"])
        total[table_name]["partitions_updated"] += int(item[table_name]["partitions_updated"])
    total["warnings"].extend(item["warnings"])


def _sorted_overview_summary(summary: dict[str, Any]) -> dict[str, Any]:
    sorted_summary = {key: value.copy() for key, value in summary.items() if key != "warnings"}
    for table_name in _OVERVIEW_TABLE_NAMES:
        sorted_summary[table_name]["affected_partitions"] = sorted(
            set(sorted_summary[table_name]["affected_partitions"])
        )
    sorted_summary["warnings"] = list(summary["warnings"])
    return sorted_summary


def _overview_has_writes(summary: dict[str, Any]) -> bool:
    return any(summary[table_name]["inserted"] > 0 for table_name in _OVERVIEW_TABLE_NAMES)
