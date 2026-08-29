"""Input selection and path-resolution helpers for the import command."""

import glob as glob_module
from pathlib import Path

import typer

from finjuice.pipeline.cli.output import ErrorCode

from .options import ImportOptions
from .rendering import (
    ImportErrorContext,
    _raise_import_error,
    render_scan_banner,
    render_scan_multiple_files,
    render_scan_no_files,
    render_scan_single_file,
)


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
        if options.emit_text:
            render_scan_single_file(candidates[0])
        confirmed = typer.confirm("이 파일을 가져올까요?", default=True)
        if confirmed:
            return candidates
        return []

    if options.emit_text:
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
