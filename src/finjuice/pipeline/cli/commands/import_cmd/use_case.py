"""Focused import command use case."""

import glob as glob_module
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import typer

from finjuice.pipeline.cli.commands.init_cmd import initialize_data_directory
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.config import Config

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
    render_zip_dry_run,
    render_zip_extracted,
    render_zip_processing_end,
    render_zip_processing_start,
)
from .result import ImportFileResults, ImportResult
from .zip_extraction import _cleanup_temp_dirs

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


def _selected_input_files(options: ImportOptions) -> list[Path]:
    """Return positional and --file inputs after --file validation."""
    selected_files = list(options.files)
    if options.file is not None:
        resolved_file = options.file.expanduser().resolve()
        if not resolved_file.exists():
            _raise_import_error(
                f"파일 없음: {options.file}",
                json_output=options.json_output,
                context=ImportErrorContext(error_code=ErrorCode.FILE_NOT_FOUND),
            )
        if resolved_file.suffix.lower() != ".xlsx":
            _raise_import_error(
                f"지원하지 않는 파일 형식: {options.file} (.xlsx 필요)",
                json_output=options.json_output,
                context=ImportErrorContext(error_code=ErrorCode.INVALID_ARGS),
            )
        selected_files.append(resolved_file)

    if selected_files:
        return selected_files

    if not options.no_scan and not options.json_output:
        discovered = _discover_downloads(options)
        if discovered:
            return discovered

    _raise_import_error(
        "입력 파일이 없습니다.",
        json_output=options.json_output,
        context=ImportErrorContext(
            error_code=ErrorCode.INVALID_ARGS,
            suggestion="finjuice import <file.xlsx|file.zip> [...]",
            hints=(
                "Usage: finjuice import <file.xlsx|file.zip> [...]",
                "       finjuice import --file <file.xlsx>",
            ),
        ),
    )


def _discover_downloads(options: ImportOptions) -> list[Path]:
    """Scan ~/Downloads for Banksalad export files and prompt for selection."""
    download_dir = Path.home() / "Downloads"
    if not download_dir.is_dir():
        return []

    from finjuice.pipeline.cli.commands.import_cmd.rendering import (
        render_scan_banner,
        render_scan_no_files,
    )

    if options.emit_text:
        render_scan_banner()

    patterns = ["뱅크샐러드_*.xlsx", "뱅크샐러드_*.zip"]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(sorted(download_dir.glob(pattern)))

    if not candidates:
        if options.emit_text:
            render_scan_no_files()
        return []

    if len(candidates) == 1:
        from finjuice.pipeline.cli.commands.import_cmd.rendering import (
            render_scan_single_file,
        )

        if options.emit_text:
            render_scan_single_file(candidates[0])
        confirmed = typer.confirm("이 파일을 가져올까요?", default=True)
        if confirmed:
            return candidates
        return []

    if options.emit_text:
        from finjuice.pipeline.cli.commands.import_cmd.rendering import (
            render_scan_multiple_files,
        )

        render_scan_multiple_files(candidates)
        choice = (
            typer.prompt(
                "가져올까요? [A(ll)/1/2/q]",
                default="a",
            )
            .strip()
            .lower()
        )

        if choice == "q":
            return []
        if choice == "a":
            return candidates
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                return [candidates[idx]]
        except ValueError:
            pass
        typer.echo("잘못된 선택. 전체 파일을 가져옵니다.")
        return candidates

    return candidates


def _resolve_input_files(selected_files: list[Path], *, json_output: bool) -> list[Path]:
    """Expand globs, validate file extensions, and deduplicate inputs."""
    valid_extensions = {".xlsx", ".zip"}
    resolved_files: list[Path] = []

    for input_file in selected_files:
        expanded = input_file.expanduser()
        if glob_module.has_magic(str(expanded)):
            resolved_files.extend(_glob_import_matches(expanded, valid_extensions))
            continue

        resolved_files.append(_resolve_literal_input(expanded, valid_extensions, json_output))

    unique_files = _deduplicate_paths(resolved_files)
    if unique_files:
        return unique_files

    _raise_import_error(
        "유효한 XLSX/ZIP 파일 없음",
        json_output=json_output,
        context=ImportErrorContext(
            error_code=ErrorCode.INVALID_ARGS,
            suggestion="finjuice import ~/Downloads/*.xlsx",
            hints=(
                "사용법: finjuice import ~/Downloads/*.xlsx",
                "       finjuice import ~/Downloads/*.zip",
            ),
        ),
    )


def _glob_import_matches(pattern: Path, valid_extensions: set[str]) -> list[Path]:
    """Return valid file matches for a glob import pattern."""
    matches: list[Path] = []
    for match in glob_module.glob(str(pattern)):
        candidate = Path(match)
        if candidate.suffix.lower() in valid_extensions and candidate.is_file():
            matches.append(candidate.resolve())
    return matches


def _resolve_literal_input(
    input_file: Path,
    valid_extensions: set[str],
    json_output: bool,
) -> Path:
    """Resolve and validate one literal input path."""
    resolved = input_file.resolve()
    if not resolved.exists():
        _raise_import_error(
            f"파일 없음: {input_file}",
            json_output=json_output,
            context=ImportErrorContext(error_code=ErrorCode.FILE_NOT_FOUND),
        )
    if resolved.suffix.lower() not in valid_extensions:
        _raise_import_error(
            f"지원하지 않는 파일 형식: {input_file} (.xlsx 또는 .zip 필요)",
            json_output=json_output,
            context=ImportErrorContext(error_code=ErrorCode.INVALID_ARGS),
        )
    return resolved


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Remove duplicate paths while preserving order."""
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique_files.append(path)
    return unique_files


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
        from finjuice.pipeline.cli.commands.doctor import (
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


def _split_import_inputs(resolved_files: list[Path]) -> tuple[list[Path], list[Path]]:
    """Split resolved import inputs into XLSX and ZIP paths."""
    xlsx_files: list[Path] = []
    zip_files: list[Path] = []
    for resolved_file in resolved_files:
        if resolved_file.suffix.lower() == ".zip":
            zip_files.append(resolved_file)
        else:
            xlsx_files.append(resolved_file)
    return xlsx_files, zip_files


def _extract_zip_inputs(
    zip_files: list[Path],
    options: ImportOptions,
    dependencies: ImportDependencies,
    temp_dirs: list[str],
) -> tuple[list[Path], int]:
    """Extract XLSX files from ZIP inputs or count archives during dry-run."""
    if not zip_files:
        return [], 0

    if options.emit_text:
        render_zip_processing_start(len(zip_files))

    effective_password = options.password or os.environ.get("FINJUICE_ZIP_PASSWORD")
    _fail_json_password_prompt(zip_files, effective_password, options, dependencies)

    extracted_files: list[Path] = []
    dry_run_zip_count = 0
    for zip_path in zip_files:
        extracted_path = _extract_one_zip(
            zip_path,
            effective_password,
            options,
            dependencies,
            temp_dirs,
        )
        if extracted_path is None:
            dry_run_zip_count += int(options.dry_run)
        else:
            extracted_files.append(extracted_path)

    if options.emit_text:
        render_zip_processing_end()

    return extracted_files, dry_run_zip_count


def _fail_json_password_prompt(
    zip_files: list[Path],
    effective_password: str | None,
    options: ImportOptions,
    dependencies: ImportDependencies,
) -> None:
    """Fail fast when JSON mode would otherwise need an interactive ZIP password."""
    if not options.json_output or effective_password is not None or options.dry_run:
        return

    if any(dependencies.zip_requires_password(zip_path) for zip_path in zip_files):
        emit_error(
            "ZIP 암호 필요. --password 또는 FINJUICE_ZIP_PASSWORD 환경변수 사용",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=True,
            command="import",
        )


def _extract_one_zip(
    zip_path: Path,
    effective_password: str | None,
    options: ImportOptions,
    dependencies: ImportDependencies,
    temp_dirs: list[str],
) -> Path | None:
    """Extract one ZIP input or render its dry-run preview."""
    if options.dry_run:
        if options.emit_text:
            render_zip_dry_run(zip_path)
        return None

    extracted = dependencies.extract_xlsx_from_zip(
        zip_path,
        password=effective_password,
        interactive=effective_password is None and not options.json_output,
        emit_text=options.emit_text,
    )
    if extracted is None:
        if options.json_output:
            _raise_import_error(
                f"ZIP 추출 실패: {zip_path.name}",
                json_output=True,
                context=ImportErrorContext(error_code=ErrorCode.GENERAL_ERROR),
            )
        _raise_import_error(
            f"ZIP 추출 실패: {zip_path.name}\n   암호가 맞는지 확인하세요.",
            json_output=False,
            context=ImportErrorContext(error_code=ErrorCode.GENERAL_ERROR),
        )

    temp_dirs.append(str(extracted.parent))
    if options.emit_text:
        render_zip_extracted(zip_path, extracted)
    return extracted


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
