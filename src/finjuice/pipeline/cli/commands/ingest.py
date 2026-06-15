"""Ingest command for finjuice CLI.

Imports XLSX files from imports/ directory into CSV partitions.
Split from pipeline.py as part of Issue #269.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config, warn_on_schema_mismatch
from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata import write_schema_version

logger = logging.getLogger(__name__)


def _render_ingest_archive_result(result: dict[str, Any]) -> None:
    """Render human-readable archive ingest result."""
    s = result["summary"]
    output.success("[OK] Re-import complete:")
    output.info(f"  New transactions: {s['new_transactions']}")
    output.info(f"  Updated: {s['updated']}")
    _render_overview_write_summary(s.get("banksalad_overview"))
    if s["skipped"] > 0:
        output.warning(f"  Skipped: {s['skipped']}")


def _render_ingest_result(result: dict[str, Any]) -> None:
    """Render human-readable standard ingest result."""
    s = result["summary"]
    output.success("[OK] Ingestion complete:")
    output.info(f"  Files processed: {s['files_processed']}")
    output.info(f"  New transactions: {s['new_transactions']}")
    output.info(f"  Updated: {s['updated']}")
    _render_overview_write_summary(s.get("banksalad_overview"))
    if s["failed"] > 0:
        output.error(f"  Failed: {s['failed']}")
        for filename, err in s.get("failed_files", []):
            output.error(f"    - {filename}: {err}")


def _render_archive_dry_run(result: dict[str, Any]) -> None:
    """Render human-readable archive dry-run preview."""
    output.info(f"Previewing archived file_id: {result['from_archive']}")
    _render_ingest_dry_run(result["preview"])


def _render_ingest_dry_run(preview: dict[str, Any]) -> None:
    """Render the human-readable ingest dry-run preview."""
    tx_preview = preview["transactions"]
    asset_preview = preview["asset_snapshots"]
    overview_preview = preview.get("banksalad_overview")

    output.info("[Dry-run Summary]")
    output.info(f"  Source XLSX files found: {preview['files_found']}")
    output.info(f"  Estimated new rows: {tx_preview['estimated_new_rows']}")
    output.info(f"  Dedup skips: {tx_preview['estimated_dedup_skips']}")
    output.info(f"  Validation skips: {tx_preview['validation_skips']}")

    for file_preview in preview["files"]:
        file_name = Path(file_preview["source_file"]).name
        output.info(
            "  "
            f"{file_name}: +{file_preview['transactions']['estimated_new_rows']} rows, "
            f"{file_preview['transactions']['estimated_dedup_skips']} dedup skips"
        )

    affected_partitions = tx_preview["affected_partitions"]
    if affected_partitions:
        output.info("  Affected partitions:")
        for partition in affected_partitions:
            output.info(f"    → {partition}")

    if asset_preview["estimated_new_rows"] > 0 or asset_preview["estimated_dedup_skips"] > 0:
        output.info(
            "  Asset snapshots: "
            f"+{asset_preview['estimated_new_rows']} rows, "
            f"{asset_preview['estimated_dedup_skips']} dedup skips"
        )

    _render_overview_preview_summary(overview_preview)

    if preview["failed"] > 0:
        output.error(f"  Failed previews: {preview['failed']}")
        for filename, err in preview["failed_files"]:
            output.error(f"    - {filename}: {err}")

    output.warning("⚠️  No changes written (dry-run mode)")


def _render_overview_preview_summary(overview_preview: dict[str, Any] | None) -> None:
    """Render privacy-safe Banksalad overview dry-run counts."""
    if not overview_preview:
        return

    total_new = sum(
        int(overview_preview[table_name]["estimated_new_rows"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    total_skipped = sum(
        int(overview_preview[table_name]["estimated_dedup_skips"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    if total_new == 0 and total_skipped == 0 and not overview_preview.get("warnings"):
        return

    output.info(
        "  Banksalad overview: "
        f"+{total_new} rows, {total_skipped} dedup skips "
        "(facts/balance/cashflow)"
    )
    if overview_preview.get("warnings"):
        output.warning(f"  Banksalad overview warnings: {len(overview_preview['warnings'])}")


def _render_overview_write_summary(overview_summary: dict[str, Any] | None) -> None:
    """Render privacy-safe Banksalad overview write counts."""
    if not overview_summary:
        return

    total_inserted = sum(
        int(overview_summary[table_name]["inserted"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    total_skipped = sum(
        int(overview_summary[table_name]["dedup_skips"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    if total_inserted == 0 and total_skipped == 0 and not overview_summary.get("warnings"):
        return

    output.info(
        "  Banksalad overview: "
        f"+{total_inserted} rows, {total_skipped} dedup skips "
        "(facts/balance/cashflow)"
    )
    if overview_summary.get("warnings"):
        output.warning(f"  Banksalad overview warnings: {len(overview_summary['warnings'])}")


def _render_standard_dry_run(result: dict[str, Any]) -> None:
    """Render human-readable standard dry-run preview."""
    _render_ingest_dry_run(result["preview"])


def ingest_command(
    ctx: typer.Context,
    from_archive: Optional[str] = typer.Option(
        None,
        "--from-archive",
        help="Re-import from archived file by file_id (e.g., '241027_1')",
    ),
    archive: bool = typer.Option(
        False,
        "--archive",
        help="Copy source XLSX files to metadata/archives/ for reproducibility",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Preview changes without writing to CSV files",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Import XLSX files from imports/ directory into CSV partitions.

    Reads all *.xlsx files from the imports directory, maps columns,
    calculates row hashes for deduplication, and writes to year/month CSV partitions.

    Examples:
        # Ingest from default location
        finjuice ingest

        # Ingest with archiving for reproducibility
        finjuice ingest --archive

        # Re-import from archived file
        finjuice ingest --from-archive 241027_1

        # Ingest from custom location
        finjuice --data-dir ~/my-finance-data ingest
    """
    from finjuice.pipeline.ingest.pipeline import (
        ingest_all_files,
        ingest_file_detailed,
        preview_ingest_all_files,
        preview_ingest_paths,
    )
    from finjuice.pipeline.metadata import get_source_file_info

    # Get config from context
    config = get_config(ctx)

    try:
        warn_on_schema_mismatch(config.data_dir)

        # Handle --from-archive mode
        if from_archive:
            _ingest_from_archive(
                config,
                from_archive,
                dry_run,
                json_output,
                get_source_file_info,
                preview_ingest_paths,
                ingest_file_detailed,
            )
            return

        # Standard ingestion mode
        _ingest_standard(
            config,
            archive,
            dry_run,
            json_output,
            preview_ingest_all_files,
            ingest_all_files,
        )

    except typer.Exit:
        raise  # Re-raise typer.Exit without modification
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Ingestion failed (%s)", type(e).__name__)
        emit_error(
            f"File access error: {e}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="ingest",
        )
    except (ValueError, KeyError, RuntimeError) as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        emit_error(
            f"Ingestion failed: {e}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="ingest",
        )
    except KeyboardInterrupt:
        emit_error(
            "Ingestion cancelled by user.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command="ingest",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Unexpected error during ingestion: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="ingest",
        )


def _ingest_from_archive(
    config: Any,
    from_archive: str,
    dry_run: bool,
    json_output: bool,
    get_source_file_info: Any,
    preview_ingest_paths: Any,
    ingest_file_detailed: Any,
) -> None:
    """Handle --from-archive ingest mode."""
    metadata_dir = config.csv_base_dir.parent / "metadata"

    # Look up file_id in import history
    import_info = get_source_file_info(metadata_dir, from_archive)

    if not import_info:
        emit_error(
            f"file_id '{from_archive}' not found in import history.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            json_output=json_output,
            command="ingest",
        )

    # Check if file is archived
    if import_info["archived"] != "yes":
        emit_error(
            f"file_id '{from_archive}' is not archived. Cannot re-import.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="ingest",
        )

    # Get archived file path
    archived_path = Path(import_info["archived_path"])

    # NOTE: Removed early existence check to prevent TOCTOU race condition (Issue #32)
    # The try-except block below handles FileNotFoundError atomically

    logger.info("Re-importing from archived file")

    if dry_run:
        preview = preview_ingest_paths([archived_path], config.csv_base_dir, archive=False)
        result = {
            "command": "ingest",
            "dry_run": True,
            "source": "archive",
            "from_archive": from_archive,
            "archive_requested": False,
            "preview": preview,
        }
        emit(result, json_output, _render_archive_dry_run, command="ingest")
        return

    if not json_output:
        output.info(f"Re-importing from archived file_id: {from_archive}")
        output.info(f"  Filename: {import_info['original_filename']}")
        output.info(f"  Original rows: {import_info['source_rows']}")

    try:
        # No early existence check - let the file operation fail atomically
        # This prevents TOCTOU race conditions (CWE-367)

        ingest_result = ingest_file_detailed(archived_path, config.csv_base_dir, archive=False)
        transactions = ingest_result["transactions"]

        result = {
            "command": "ingest",
            "dry_run": False,
            "source": "archive",
            "from_archive": from_archive,
            "summary": {
                "files_processed": 1,
                "new_transactions": int(transactions["inserted"]),
                "updated": int(transactions["dedup_skips"]),
                "skipped": int(transactions["validation_skips"]),
                "banksalad_overview": ingest_result["banksalad_overview"],
            },
        }
        write_schema_version(config.data_dir, SCHEMA_VERSION)
        emit(result, json_output, _render_ingest_archive_result, command="ingest")

    except FileNotFoundError as e:
        logger.error(f"Archive file not found: {e}")
        emit_error(
            f"Archive file not found at {archived_path}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            json_output=json_output,
            command="ingest",
        )


def _ingest_standard(
    config: Any,
    archive: bool,
    dry_run: bool,
    json_output: bool,
    preview_ingest_all_files: Any,
    ingest_all_files: Any,
) -> None:
    """Handle standard ingest mode."""
    logger.info(f"CSV partitions: {config.csv_base_dir}")

    if archive:
        logger.info("Archiving enabled: source files will be copied to metadata/archives/")

    if dry_run:
        preview = preview_ingest_all_files(config.import_dir, config.csv_base_dir, archive=archive)
        result = {
            "command": "ingest",
            "dry_run": True,
            "source": "imports",
            "archive_requested": archive,
            "preview": preview,
        }
        emit(result, json_output, _render_standard_dry_run, command="ingest")
        return

    summary = ingest_all_files(config.import_dir, config.csv_base_dir, archive=archive)

    result = {
        "command": "ingest",
        "dry_run": False,
        "source": "imports",
        "archive_requested": archive,
        "summary": {
            "files_processed": summary["files"],
            "new_transactions": summary["inserted"],
            "updated": summary["updated"],
            "banksalad_overview": summary.get("banksalad_overview", {}),
            "failed": summary["failed"],
            "failed_files": summary.get("failed_files", []),
        },
    }
    write_schema_version(config.data_dir, SCHEMA_VERSION)
    emit(result, json_output, _render_ingest_result, command="ingest")
