"""Ingest command for finjuice CLI.

Imports XLSX files from imports/ into the selected storage authority.
Split from pipeline.py as part of Issue #269.
Human rendering lives in :mod:`finjuice.pipeline.cli.commands.ingest_rendering`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.ingest_rendering import (
    _render_archive_dry_run,
    _render_ingest_archive_result,
    _render_ingest_result,
    _render_repository_ingest,
    _render_standard_dry_run,
)
from finjuice.pipeline.cli.mutation_options import with_mutation_options
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.pipeline_failure import FullPipelineError
from finjuice.pipeline.cli.repository_import import (
    identity_from_context,
    ingest_archived_source,
    ingest_import_directory,
)
from finjuice.pipeline.cli.utils import get_config, get_mutation_facade, warn_on_schema_mismatch
from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata import write_schema_version
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationValidationError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepositoryIngestOptions:
    """Presentation and source options for authoritative ingestion."""

    from_archive: str | None
    archive: bool
    dry_run: bool
    json_output: bool
    force: bool = False
    only_unprocessed: bool = False


@dataclass(frozen=True)
class _StandardIngestRequest:
    archive: bool
    dry_run: bool
    json_output: bool
    force: bool
    only_unprocessed: bool


@dataclass(frozen=True)
class _IngestRequest:
    """Every public ingest flag for one invocation, before authority routing."""

    from_archive: str | None
    archive: bool
    dry_run: bool
    json_output: bool
    force: bool
    only_unprocessed: bool

    def repository_options(self) -> RepositoryIngestOptions:
        return RepositoryIngestOptions(
            self.from_archive,
            self.archive,
            self.dry_run,
            self.json_output,
            force=self.force,
            only_unprocessed=self.only_unprocessed,
        )

    def standard_request(self) -> _StandardIngestRequest:
        return _StandardIngestRequest(
            archive=self.archive,
            dry_run=self.dry_run,
            json_output=self.json_output,
            force=self.force,
            only_unprocessed=self.only_unprocessed,
        )


@with_mutation_options
def ingest_command(  # noqa: PLR0913 - Typer command signature mirrors public CLI flags.
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
        help="Preview ingestion without writing data",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reparse legacy workbooks in import history; SQLite keeps content deduplication",
    ),
    only_unprocessed: bool = typer.Option(
        False,
        "--only-unprocessed",
        help="Skip processed files (legacy: filename history; SQLite: content identity)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Import XLSX files from imports/ into the selected storage authority.

    Reads all *.xlsx files from the imports directory, maps columns,
    and deduplicates them. Legacy storage writes year/month CSV partitions;
    active SQLite storage preserves original bytes and canonical records.

    Examples:
        # Ingest from default location
        finjuice ingest

        # Ingest with archiving for reproducibility
        finjuice ingest --archive

        # Re-import from archived file
        finjuice ingest --from-archive 241027_1

        # Ingest from custom location
        finjuice --data-dir ~/my-finance-data ingest

        # Preview unprocessed files using the selected storage authority
        finjuice ingest --dry-run --json

        # Ingest only unprocessed files
        finjuice ingest --only-unprocessed
    """
    # Get config from context
    config = get_config(ctx)
    request = _IngestRequest(
        from_archive=from_archive,
        archive=archive,
        dry_run=dry_run,
        json_output=json_output,
        force=force,
        only_unprocessed=only_unprocessed,
    )

    try:
        _dispatch_ingest(ctx, config, request)

    except typer.Exit:
        raise  # Re-raise typer.Exit without modification
    except FullPipelineError as exc:
        emit_error(
            str(exc),
            error_code=exc.error_code,
            exit_code=exc.exit_code,
            json_output=json_output,
            command="ingest",
            meta_extras=exc.metadata(),
        )
    except MutationValidationError as e:
        emit_error(
            str(e),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="ingest",
        )
    except MutationConflictError as e:
        emit_error(
            str(e),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="ingest",
        )
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


def _reject_conflicting_history_flags(request: _IngestRequest) -> None:
    """Reject --force with --only-unprocessed before any authority is selected."""
    if not (request.force and request.only_unprocessed):
        return
    emit_error(
        "--force and --only-unprocessed cannot be combined.",
        error_code=ErrorCode.INVALID_ARGS,
        exit_code=ExitCode.USAGE_ERROR,
        json_output=request.json_output,
        command="ingest",
    )


def _dispatch_ingest(ctx: typer.Context, config: Any, request: _IngestRequest) -> None:
    """Route one invocation to the active, archived, or legacy ingest path."""
    from finjuice.pipeline.ingest.pipeline import (
        ingest_file_detailed,
        preview_ingest_paths,
    )
    from finjuice.pipeline.metadata import get_source_file_info

    _reject_conflicting_history_flags(request)

    facade = get_mutation_facade(ctx, config)
    if isinstance(facade.dispatch().authority, RepositoryAuthority):
        _ingest_repository(ctx, config, facade, request.repository_options())
        return

    warn_on_schema_mismatch(config.data_dir)

    if request.from_archive:
        _ingest_from_archive(
            config,
            request.from_archive,
            request.dry_run,
            request.json_output,
            get_source_file_info,
            preview_ingest_paths,
            ingest_file_detailed,
        )
        return

    _ingest_standard(config, request.standard_request())


def _ingest_repository(
    ctx: typer.Context,
    config: Any,
    facade: Any,
    options: RepositoryIngestOptions,
) -> None:
    """Ingest through exact import without legacy archive, history, or schema writes."""
    identity = identity_from_context(ctx)
    result = _repository_ingest_result(config, facade, options, identity)
    result.update(_canonical_filter_counts(result, options))
    if int(result["summary"]["failed"]) > 0:
        failure = FullPipelineError("ingest", {"ingest": result}, error_type="PartialIngestFailure")
        emit_error(
            str(failure),
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=options.json_output,
            command="ingest",
            meta_extras=failure.metadata(),
        )
    emit(result, options.json_output, _render_repository_ingest, command="ingest")


def _repository_ingest_result(
    config: Any,
    facade: Any,
    options: RepositoryIngestOptions,
    identity: Any,
) -> dict[str, Any]:
    if options.from_archive:
        return ingest_archived_source(
            facade,
            options.from_archive,
            identity,
            preview=options.dry_run,
            archive_requested=options.archive,
        )
    return ingest_import_directory(
        facade, config, identity, preview=options.dry_run, archive_requested=options.archive
    )


def _canonical_filter_counts(
    result: dict[str, Any], options: RepositoryIngestOptions
) -> dict[str, int]:
    """Report canonical byte-identity reuse, never filename-based history skips.

    Under active authority every staged workbook is submitted to the exact
    import domain, so ``history_skipped`` counts files whose exact bytes were
    already recorded and ``would_parse`` counts files carrying new bytes. A
    reused filename with different bytes therefore still counts as new work.
    """
    if options.force or not (options.dry_run or options.only_unprocessed):
        return {"history_skipped": 0, "would_parse": len(result.get("receipts", []))}
    receipts = result.get("receipts", [])
    already_recorded = sum(
        1 for receipt in receipts if receipt.get("result", {}).get("noop") is True
    )
    return {
        "history_skipped": already_recorded,
        "would_parse": len(receipts) - already_recorded,
    }


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


def _select_standard_ingest_paths(
    config: Any, request: _StandardIngestRequest
) -> tuple[list[Path], int]:
    """Return workbooks to parse and how many history hits were skipped."""
    from finjuice.pipeline.metadata.import_history_helpers import list_unprocessed_xlsx

    staged = list(config.import_dir.glob("*.xlsx"))
    if request.force or not (request.dry_run or request.only_unprocessed):
        return staged, 0
    selected = list_unprocessed_xlsx(config.import_dir, config.data_dir / "metadata")
    return selected, len(staged) - len(selected)


def _ingest_standard(
    config: Any,
    request: _StandardIngestRequest,
) -> None:
    """Handle standard ingest mode."""
    from finjuice.pipeline.ingest.pipeline import (
        ingest_all_files,
        ingest_paths,
        preview_ingest_all_files,
    )

    logger.info(f"CSV partitions: {config.csv_base_dir}")

    if request.archive:
        logger.info("Archiving enabled: source files will be copied to metadata/archives/")

    selected, skipped = _select_standard_ingest_paths(config, request)

    if request.dry_run:
        preview = preview_ingest_all_files(
            config.import_dir,
            config.csv_base_dir,
            archive=request.archive,
            skip_processed=not request.force,
            metadata_dir=config.data_dir / "metadata",
        )
        result = {
            "command": "ingest",
            "dry_run": True,
            "source": "imports",
            "archive_requested": request.archive,
            "history_skipped": preview.get("history_skipped", skipped),
            "would_parse": preview.get("would_parse", len(selected)),
            "preview": preview,
        }
        emit(result, request.json_output, _render_standard_dry_run, command="ingest")
        return

    if request.only_unprocessed:
        summary = ingest_paths(selected, config.csv_base_dir, archive=request.archive)
    else:
        summary = ingest_all_files(config.import_dir, config.csv_base_dir, archive=request.archive)

    result = {
        "command": "ingest",
        "dry_run": False,
        "source": "imports",
        "archive_requested": request.archive,
        "history_skipped": skipped,
        "would_parse": len(selected),
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
    emit(result, request.json_output, _render_ingest_result, command="ingest")
