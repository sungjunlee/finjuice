"""Pre-load file and sheet-name guards for Banksalad XLSX validation.

Owns sheet-index bounds, missing-file, and oversized-file error messages.
XLSX load/schema validation stays in
:mod:`finjuice.pipeline.validation.validators`, which re-exports these helpers
so existing callers can keep importing from this module.
"""

from __future__ import annotations

from pathlib import Path

# Security constants
MAX_FILE_SIZE_MB = 100  # Maximum file size to prevent memory exhaustion


def _sheet_name_error_message(sheet_name: str | int) -> str | None:
    """Return an error message when ``sheet_name`` is an out-of-range index.

    Args:
        sheet_name: Sheet name or 0-based index supplied by the caller.

    Returns:
        Error message for a negative or excessively large index, otherwise None.
    """
    if not isinstance(sheet_name, int):
        return None
    if sheet_name < 0:
        return "❌ sheet_name은 0 이상이어야 합니다."
    if sheet_name > 100:  # Reasonable upper bound
        return "❌ sheet_name이 너무 큽니다 (최대: 100)."
    return None


def _missing_file_error_message(file_path: Path) -> str | None:
    """Return an error message when the XLSX path does not exist.

    Args:
        file_path: Path to the XLSX file.

    Returns:
        Error message containing only the filename, otherwise None.
    """
    if file_path.exists():
        return None
    return f"❌ 파일을 찾을 수 없습니다: {file_path.name}"


def _oversized_file_error_message(file_path: Path) -> str | None:
    """Return an error message when the XLSX exceeds ``MAX_FILE_SIZE_MB``.

    Args:
        file_path: Existing path to the XLSX file.

    Returns:
        Error message with size guidance, otherwise None.
    """
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb <= MAX_FILE_SIZE_MB:
        return None
    return (
        f"❌ 파일 크기가 너무 큽니다: {file_size_mb:.1f}MB "
        f"(최대: {MAX_FILE_SIZE_MB}MB)\n"
        f"💡 파일을 분할하거나 기간을 나누어 export 해주세요."
    )
