"""
Validation functions for Banksalad XLSX files (Polars-only).

Provides comprehensive validation with clear error messages and suggestions
for fixing common issues.

Column-name matching helpers live in
:mod:`finjuice.pipeline.validation.validators_helpers` and are re-exported
here so existing callers can keep importing from this module.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile

import polars as pl

from finjuice.pipeline.ingest.schemas import REQUIRED_KOREAN_COLUMNS
from finjuice.pipeline.validation.validators_helpers import (
    MAX_COLUMN_NAME_LENGTH,  # noqa: F401 — re-exported for existing validators imports
    _sanitize_column_names,
    _suggest_column_mapping,
)

logger = logging.getLogger(__name__)

# Security constants
MAX_FILE_SIZE_MB = 100  # Maximum file size to prevent memory exhaustion


class ValidationError(ValueError):
    """Custom exception for schema validation errors."""


@dataclass
class ValidationResult:
    """Result of XLSX validation."""

    is_valid: bool
    error_message: Optional[str] = None
    warnings: list[str] = None  # type: ignore
    suggestions: dict[str, str] = None  # type: ignore
    sheet_name: Optional[str] = None
    row_count: int = 0

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.warnings is None:
            self.warnings = []
        if self.suggestions is None:
            self.suggestions = {}


def validate_banksalad_xlsx(
    file_path: Path,
    sheet_name: str | int = 1,
    strict: bool = False,
) -> ValidationResult:
    """
    Validate Banksalad XLSX file before import.

    Performs the following validations:
    1. File exists and is readable
    2. Sheet exists and can be loaded
    3. Required columns are present
    4. Column names match expected schema (with suggestions for typos)
    5. Basic data quality checks (optional with strict=True)

    Args:
        file_path: Path to XLSX file to validate
        sheet_name: Sheet name or index (default: 1 for "가계부 내역")
        strict: If True, perform additional data quality checks (default: False)

    Returns:
        ValidationResult: Validation result with error messages and suggestions

    Example:
        >>> result = validate_banksalad_xlsx(Path("data.xlsx"))
        >>> if not result.is_valid:
        ...     print(result.error_message)
        ...     print("Suggestions:", result.suggestions)
    """
    # 0. Validate sheet_name parameter
    if isinstance(sheet_name, int):
        if sheet_name < 0:
            return ValidationResult(
                is_valid=False,
                error_message="❌ sheet_name은 0 이상이어야 합니다.",
            )
        if sheet_name > 100:  # Reasonable upper bound
            return ValidationResult(
                is_valid=False,
                error_message="❌ sheet_name이 너무 큽니다 (최대: 100).",
            )

    # 1. File existence check
    if not file_path.exists():
        return ValidationResult(
            is_valid=False,
            error_message=f"❌ 파일을 찾을 수 없습니다: {file_path.name}",
        )

    # 2. File size check (prevent memory exhaustion)
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        return ValidationResult(
            is_valid=False,
            error_message=(
                f"❌ 파일 크기가 너무 큽니다: {file_size_mb:.1f}MB "
                f"(최대: {MAX_FILE_SIZE_MB}MB)\n"
                f"💡 파일을 분할하거나 기간을 나누어 export 해주세요."
            ),
        )

    # 3. Try to load Excel file (Polars)
    # Note: Polars sheet_id is 1-indexed (1=first sheet, 2=second sheet)
    # Polars sheet_name parameter accepts string names
    try:
        if isinstance(sheet_name, str):
            # Use sheet_name parameter for string names
            df = pl.read_excel(
                file_path, sheet_name=sheet_name, engine="openpyxl", raise_if_empty=False
            )
        else:
            # Convert 0-indexed to 1-indexed for sheet_id
            sheet_id = sheet_name + 1 if sheet_name >= 0 else 1
            df = pl.read_excel(
                file_path, sheet_id=sheet_id, engine="openpyxl", raise_if_empty=False
            )
        actual_sheet = sheet_name
    except (PermissionError, OSError, ValueError, BadZipFile, pl.exceptions.PolarsError) as e:
        error_str = str(e)
        # Sheet doesn't exist - try to suggest correct sheet
        if "Worksheet" in error_str or "sheet" in error_str.lower():
            return ValidationResult(
                is_valid=False,
                error_message=f"❌ 시트를 찾을 수 없습니다: {sheet_name}\n"
                f"💡 뱅크샐러드 export 파일의 거래 내역은 보통 2번째 시트 (index 1)에 있습니다.\n"
                f"   sheet_name=1 또는 sheet_name='가계부 내역'을 사용해보세요.",
            )
        return ValidationResult(
            is_valid=False,
            error_message=f"❌ 파일 읽기 실패: {e}\n"
            f"💡 파일이 손상되었거나 Excel 형식이 아닐 수 있습니다.",
        )

    # 3. Check required columns (shares REQUIRED_KOREAN_COLUMNS with ingest schemas
    # to avoid drift between validation and column mapping).
    actual_cols = set(df.columns)
    missing_cols = set(REQUIRED_KOREAN_COLUMNS) - actual_cols

    if missing_cols:
        # Try to find similar column names
        suggestions = _suggest_column_mapping(missing_cols, actual_cols)

        error_parts = [f"❌ 필수 컬럼이 누락되었습니다: {', '.join(sorted(missing_cols))}"]

        if suggestions:
            error_parts.append("\n💡 유사한 컬럼명이 발견되었습니다:")
            for missing, similar in suggestions.items():
                error_parts.append(f"   • '{missing}' → '{similar}'?")
            error_parts.append(
                "\n컬럼명을 확인하거나, 뱅크샐러드 최신 export 형식인지 확인해주세요."
            )
        else:
            error_parts.append(
                "\n💡 뱅크샐러드 export 파일의 필수 컬럼:\n"
                "   • 날짜 (거래일)\n"
                "   • 시간\n"
                "   • 타입 (지출/수입/이체)\n"
                "   • 금액\n"
                "   • 결제수단 (계좌/카드)\n"
                "\n현재 파일의 컬럼:\n"
                f"   {_sanitize_column_names(actual_cols)}"
            )

        return ValidationResult(
            is_valid=False,
            error_message="".join(error_parts),
            suggestions=suggestions,
        )

    # 4. Optional: Check for extra unexpected columns (warnings only)
    warnings = []
    expected_cols = {
        "날짜",
        "시간",
        "타입",
        "대분류",
        "소분류",
        "내용",
        "메모",
        "금액",
        "화폐",
        "결제수단",
    }
    extra_cols = actual_cols - expected_cols
    if extra_cols:
        warnings.append(
            f"⚠️  예상하지 못한 컬럼이 있습니다 (무시됩니다): {_sanitize_column_names(extra_cols)}"
        )

    # 5. Strict mode: Basic data quality checks (Polars)
    if strict:
        try:
            # Check date column is not empty
            if df["날짜"].is_null().all():
                return ValidationResult(
                    is_valid=False,
                    error_message="❌ '날짜' 컬럼이 비어있습니다.",
                )

            # Check amount column is numeric
            amount_dtype = df["금액"].dtype
            if not (amount_dtype.is_numeric() or amount_dtype == pl.Utf8):
                warnings.append("⚠️  '금액' 컬럼이 숫자 형식이 아닙니다. 변환을 시도합니다.")

            # Check for completely empty rows (all columns are null)
            # Polars: filter rows where all columns are null
            null_counts_per_row = df.select(pl.all().is_null().cast(pl.Int32)).sum_horizontal()
            empty_rows = (null_counts_per_row == len(df.columns)).sum()
            if empty_rows > 0:
                warnings.append(f"⚠️  빈 행이 {empty_rows}개 있습니다 (건너뜁니다).")

        except KeyError as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"❌ 데이터 품질 검사 실패: {e}",
            )

    # All checks passed!
    return ValidationResult(
        is_valid=True,
        warnings=warnings,
        sheet_name=str(actual_sheet),
        row_count=len(df),
    )


def validate_banksalad_xlsx_polars(
    file_path: Path,
    sheet_id: int = 1,
    strict: bool = False,
) -> ValidationResult:
    """
    Validate Banksalad XLSX file using Polars.

    This is an alias for validate_banksalad_xlsx() since the main function
    now uses Polars natively.

    Args:
        file_path: Path to XLSX file
        sheet_id: Sheet index (default: 1)
        strict: Enable strict data quality checks

    Returns:
        ValidationResult: Validation result
    """
    # Main function now uses Polars natively
    return validate_banksalad_xlsx(file_path, sheet_name=sheet_id, strict=strict)
