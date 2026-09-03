"""XLSX workbook load helpers for Banksalad validation.

Owns Polars Excel sheet reads and load-failure error messages.
Schema and data-quality checks stay in
:mod:`finjuice.pipeline.validation.validators`, which re-exports these helpers
so existing callers can keep importing from this module.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl


def _load_banksalad_xlsx(file_path: Path, sheet_name: str | int) -> pl.DataFrame:
    """Read the requested Banksalad XLSX sheet with Polars.

    Polars ``sheet_id`` is 1-indexed (1=first sheet). Callers pass a 0-based
    integer index or a sheet name string.

    Args:
        file_path: Existing path to the XLSX file.
        sheet_name: Sheet name or 0-based index supplied by the caller.

    Returns:
        DataFrame for the requested sheet.

    Raises:
        PermissionError, OSError, ValueError, zipfile.BadZipFile,
        polars.exceptions.PolarsError: When the workbook cannot be opened or
        the sheet does not exist.
    """
    if isinstance(sheet_name, str):
        return pl.read_excel(
            file_path, sheet_name=sheet_name, engine="openpyxl", raise_if_empty=False
        )
    # Convert 0-indexed to 1-indexed for sheet_id
    sheet_id = sheet_name + 1 if sheet_name >= 0 else 1
    return pl.read_excel(file_path, sheet_id=sheet_id, engine="openpyxl", raise_if_empty=False)


def _xlsx_load_error_message(exc: Exception, sheet_name: str | int) -> str:
    """Map a workbook-load exception to a user-facing error message.

    Args:
        exc: Exception raised while reading the XLSX.
        sheet_name: Sheet name or 0-based index that was requested.

    Returns:
        Korean error message with a recovery hint.
    """
    error_str = str(exc)
    if "Worksheet" in error_str or "sheet" in error_str.lower():
        return (
            f"❌ 시트를 찾을 수 없습니다: {sheet_name}\n"
            f"💡 뱅크샐러드 export 파일의 거래 내역은 보통 2번째 시트 (index 1)에 있습니다.\n"
            f"   sheet_name=1 또는 sheet_name='가계부 내역'을 사용해보세요."
        )
    return f"❌ 파일 읽기 실패: {exc}\n💡 파일이 손상되었거나 Excel 형식이 아닐 수 있습니다."
