"""Focused import command use case.

Owns import orchestration, dependency protocols, first-run init, and
copy/pipeline execution. ZIP input splitting and per-archive extraction
live in
:mod:`finjuice.pipeline.cli.commands.import_cmd.use_case_helpers`
and are re-exported here so existing callers can keep importing from this
module.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import typer

from finjuice.pipeline.cli.commands.init_helpers import initialize_data_directory
from finjuice.pipeline.cli.output import ErrorCode
from finjuice.pipeline.config import Config

from .inputs import _resolve_input_files, _selected_input_files
from .options import ImportOptions
from .rendering import (
    ImportErrorContext,
    _build_import_result,
    _raise_import_error,
    render_all_files_skipped,
    render_before_copy_error,
    render_before_pipeline_error,
    render_copy_results,
    render_dry_run_summary,
    render_final_summary,
    render_first_run_initialized,
    render_import_mode,
)
from .result import ImportFileResults, ImportResult
from .use_case_helpers import _split_import_inputs
from .zip_extraction import _cleanup_temp_dirs
from .zip_inputs import (
    _extract_one_zip,  # noqa: F401 — re-exported for existing use_case imports
    _extract_zip_inputs,
    _fail_json_password_prompt,  # noqa: F401 — re-exported for existing use_case imports
)

logger = logging.getLogger(__name__)


class ImportFilesFn(Protocol):
    """Callable shape for the XLSX copy helper."""

    def __call__(
        self,
        files: list[Path],
        imports_dir: Path,
        force: bool = False,
        dry_run: bool = False,
    ) -> ImportFileResults: ...


class ExtractZipFn(Protocol):
    """Callable shape for the ZIP extraction helper."""

    def __call__(
        self,
        zip_path: Path,
        password: str | None = None,
        interactive: bool = True,
        emit_text: bool = True,
    ) -> Path | None: ...


class RunPipelineFn(Protocol):
    """Callable shape for the full-pipeline helper."""

    def __call__(
        self,
        ctx: typer.Context,
        config: Config,
        *,
        emit_text: bool = True,
    ) -> dict[str, Any]: ...


class FirstRunFn(Protocol):
    """Callable shape for first-run detection."""

    def __call__(self, data_dir: Path) -> bool: ...


class ZipRequiresPasswordFn(Protocol):
    """Callable shape for encrypted ZIP detection."""

    def __call__(self, zip_path: Path) -> bool: ...


@dataclass(frozen=True)
class ImportDependencies:
    """Import use-case dependencies exposed for compatibility patching."""

    is_first_run: FirstRunFn
    import_xlsx_files: ImportFilesFn
    extract_xlsx_from_zip: ExtractZipFn
    zip_requires_password: ZipRequiresPasswordFn
    run_full_pipeline: RunPipelineFn


def run_import(options: ImportOptions, *, dependencies: ImportDependencies) -> ImportResult:
    """Run import orchestration and return the final CLI result payload."""
    temp_dirs: list[str] = []
    try:
        selected_files = _selected_input_files(options)
        resolved_files = _resolve_input_files(selected_files, json_output=options.json_output)
        _ensure_initialized(options, dependencies)
        xlsx_files, zip_files = _split_import_inputs(resolved_files)
        extracted_files, dry_run_zip_count = _extract_zip_inputs(
            zip_files,
            options,
            dependencies,
            temp_dirs,
        )
        return _copy_and_maybe_run_pipeline(
            [*xlsx_files, *extracted_files],
            dry_run_zip_count,
            options,
            dependencies,
        )
    finally:
        _cleanup_temp_dirs(temp_dirs)


def _ensure_initialized(options: ImportOptions, dependencies: ImportDependencies) -> None:
    """Auto-initialize the data directory on first import."""
    try:
        if not dependencies.is_first_run(options.config.data_dir):
            return

        initialize_data_directory(options.config, with_git=True, with_agents=False)
        if options.emit_text:
            render_first_run_initialized(options.config.data_dir)
        logger.info("Auto-initialized data directory")
        _run_quick_doctor(options)
    except (OSError, PermissionError) as exc:
        logger.error(f"Failed to initialize data directory: {exc}")
        _raise_import_error(
            f"디렉토리 생성 실패: {exc}",
            json_output=options.json_output,
            context=ImportErrorContext(error_code=ErrorCode.GENERAL_ERROR),
        )


def _run_quick_doctor(options: ImportOptions) -> None:
    """Run lightweight dependency check after auto-init, continue regardless."""
    try:
        from finjuice.pipeline.doctor import (
            _check_analytics_duckdb,
            _check_dependencies,
        )

        analytics_results, _missing_extras, install_hint = _check_analytics_duckdb()
        dep_results = _check_dependencies()

        warnings = []
        for check in analytics_results:
            if check.status == "warning":
                warnings.append((check.message, check.suggestion))
        for check in dep_results:
            if check.status == "warning":
                warnings.append((check.message, check.suggestion))

        if warnings:
            logger.info("Quick doctor found %d warning(s)", len(warnings))
            if options.emit_text:
                from finjuice.pipeline.cli.output import console as rich_console

                rich_console.print()
                for msg, suggestion in warnings:
                    rich_console.print(f"  ⚠️  [yellow]{msg}[/yellow]")
                    if suggestion:
                        rich_console.print(f"     → [green]{suggestion}[/green]")
                rich_console.print()
    except Exception:
        logger.debug("Quick doctor check failed (non-fatal)", exc_info=True)


def _copy_and_maybe_run_pipeline(
    resolved_files: list[Path],
    dry_run_zip_count: int,
    options: ImportOptions,
    dependencies: ImportDependencies,
) -> ImportResult:
    """Copy prepared XLSX files and optionally execute the full pipeline."""
    if options.emit_text:
        render_import_mode(dry_run=options.dry_run, file_count=len(resolved_files))

    results = dependencies.import_xlsx_files(
        files=resolved_files,
        imports_dir=options.config.import_dir,
        force=options.force,
        dry_run=options.dry_run,
    )
    if options.emit_text:
        render_copy_results(results, dry_run=options.dry_run)

    imported_count = len(results["imported"])
    skipped_count = len(results["skipped"])
    error_count = len(results["errors"])
    _fail_copy_errors(results, error_count, options)
    _render_all_skipped_if_needed(imported_count, skipped_count, options)

    if options.dry_run:
        return _dry_run_result(
            imported_count,
            skipped_count,
            error_count,
            dry_run_zip_count,
            options,
        )

    return _run_pipeline_after_copy(
        imported_count,
        skipped_count,
        error_count,
        options,
        dependencies,
    )


def _fail_copy_errors(
    results: ImportFileResults,
    error_count: int,
    options: ImportOptions,
) -> None:
    """Exit on copy-step errors."""
    if error_count == 0:
        return

    error_details = "; ".join(
        f"{src.name}: {error_message}" for src, error_message in results["errors"]
    )
    if options.emit_text:
        render_before_copy_error()
    _raise_import_error(
        f"{error_count}개 오류 발생",
        json_output=options.json_output,
        context=ImportErrorContext(
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            suggestion=error_details or None,
        ),
    )


def _render_all_skipped_if_needed(
    imported_count: int,
    skipped_count: int,
    options: ImportOptions,
) -> None:
    """Render all-skipped copy message when applicable."""
    if imported_count == 0 and skipped_count > 0 and options.emit_text:
        render_all_files_skipped(skipped_count, dry_run=options.dry_run)


def _dry_run_result(
    imported_count: int,
    skipped_count: int,
    error_count: int,
    dry_run_zip_count: int,
    options: ImportOptions,
) -> ImportResult:
    """Build the dry-run import result."""
    if options.emit_text:
        render_dry_run_summary(imported_count, options.config.import_dir)
    return ImportResult(
        payload={
            "files_processed": imported_count + dry_run_zip_count,
            "files_skipped": skipped_count,
            "errors": error_count,
            "dry_run": True,
        },
        dry_run=True,
    )


def _run_pipeline_after_copy(
    imported_count: int,
    skipped_count: int,
    error_count: int,
    options: ImportOptions,
    dependencies: ImportDependencies,
) -> ImportResult:
    """Run the pipeline after successful copy and build the final result."""
    try:
        summary = dependencies.run_full_pipeline(
            options.ctx,
            options.config,
            emit_text=options.emit_text,
        )
        if options.emit_text:
            render_final_summary(summary, imported_count=imported_count, config=options.config)
        return ImportResult(
            payload=_build_import_result(summary, imported_count, skipped_count, error_count),
            dry_run=False,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error(f"Pipeline failed: {exc}", exc_info=True)
        if options.emit_text:
            render_before_pipeline_error()
        _raise_import_error(
            f"파이프라인 실패: {exc}",
            json_output=options.json_output,
            context=ImportErrorContext(error_code=ErrorCode.GENERAL_ERROR),
        )
