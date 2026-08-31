"""ZIP input preparation helpers for the import use case."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error

from .rendering import (
    ImportErrorContext,
    _raise_import_error,
    render_zip_dry_run,
    render_zip_extracted,
    render_zip_processing_end,
    render_zip_processing_start,
)

if TYPE_CHECKING:
    from .options import ImportOptions
    from .use_case import ImportDependencies


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
