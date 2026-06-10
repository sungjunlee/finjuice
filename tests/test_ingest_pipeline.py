"""
Tests for XLSX Ingestion Pipeline.

Tests end-to-end ingestion pipeline including schema mapping, deduplication,
and CSV partition storage.
"""

import tempfile
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.ingest._normalize import _normalize_amount
from finjuice.pipeline.ingest.pipeline import (
    ingest_all_files,
    ingest_file,
)
from finjuice.pipeline.storage import csv_partition


def write_banksalad_xlsx(df: pl.DataFrame, file_path: Path) -> None:
    """Write DataFrame to XLSX in Banksalad format (2 sheets).

    Banksalad exports have 2 sheets:
    - Sheet 0 ("요약"): Summary data
    - Sheet 1 ("가계부 내역"): Transaction details

    The ingest pipeline expects transaction data in sheet 1 (index 1).
    """
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)

    # Sheet 1: Summary
    summary_sheet = workbook.add_worksheet("요약")
    summary_sheet.write(0, 0, "요약")
    summary_sheet.write(1, 0, "테스트 데이터")

    # Sheet 2: Transaction details
    detail_sheet = workbook.add_worksheet("가계부 내역")
    # Write header
    for col_idx, col_name in enumerate(df.columns):
        detail_sheet.write(0, col_idx, col_name)
    # Write data
    for row_idx, row in enumerate(df.iter_rows(named=False)):
        for col_idx, value in enumerate(row):
            detail_sheet.write(row_idx + 1, col_idx, value)

    workbook.close()


@pytest.fixture
def temp_import_dir():
    """Create a temporary import directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_xlsx_file(temp_import_dir):
    """Create a sample XLSX file with test data in Banksalad format.

    Note: Banksalad exports have 2 sheets:
    - Sheet 0 ("요약"): Summary data
    - Sheet 1 ("가계부 내역"): Transaction details

    The ingest pipeline expects transaction data in sheet 1 (index 1).
    """
    df = pl.DataFrame(
        {
            "날짜": ["2025-10-27", "2025-10-28", "2025-10-29"],
            "시간": ["19:24", "08:30", "12:45"],
            "타입": ["지출", "수입", "지출"],
            "대분류": ["식비", "급여", "교통"],
            "중분류": ["카페", "월급", "지하철"],
            "내용": ["스타벅스", "회사", "교통카드"],
            "메모": ["회의", "", "출퇴근"],
            "금액": [-5000, 3000000, -1500],
            "화폐": ["KRW", "KRW", "KRW"],
            "결제수단": ["체크카드", "은행계좌", "교통카드"],
        }
    )

    file_path = temp_import_dir / "test_data.xlsx"
    write_banksalad_xlsx(df, file_path)
    return file_path


class TestNormalizeAmount:
    """Test amount normalization and validation."""

    def test_normalize_expense_negative(self):
        """Test that expense with negative amount is preserved."""
        # Arrange
        amount = -5000
        type_raw = "지출"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == -5000

    def test_normalize_expense_positive_is_refund(self):
        """Test that expense with positive amount is treated as refund (kept positive)."""
        # Arrange - Banksalad marks refunds as "지출" with positive amount
        amount = 5000
        type_raw = "지출"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert - Keep positive so it reduces total spending in aggregations
        assert result == 5000

    def test_normalize_income_positive(self):
        """Test that income with positive amount is preserved."""
        # Arrange
        amount = 100000
        type_raw = "수입"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == 100000

    def test_normalize_income_negative_converts(self):
        """Test that income with negative amount is converted to positive."""
        # Arrange
        amount = -100000
        type_raw = "수입"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == 100000

    def test_normalize_transfer_preserves_sign(self):
        """Test that transfer amount sign is preserved (can be either)."""
        # Arrange
        amount_negative = -50000
        amount_positive = 50000
        type_raw = "이체"

        # Act
        result_neg = _normalize_amount(amount_negative, type_raw)
        result_pos = _normalize_amount(amount_positive, type_raw)

        # Assert
        assert result_neg == -50000
        assert result_pos == 50000

    def test_normalize_출금_type(self):  # noqa: N802
        """Test normalization with '출금' (withdrawal) type - positive is refund."""
        # Arrange - positive 출금 is a refund/reversal
        amount = 10000
        type_raw = "출금"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert - Keep positive (refund reduces total spend)
        assert result == 10000

    def test_normalize_입금_type(self):  # noqa: N802
        """Test normalization with '입금' (deposit) type."""
        # Arrange
        amount = -10000
        type_raw = "입금"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == 10000

    def test_normalize_unknown_type_preserves(self):
        """Test that unknown type preserves amount as-is."""
        # Arrange
        amount = -5000
        type_raw = "UNKNOWN_TYPE"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == -5000

    def test_normalize_zero_amount(self):
        """Test normalization of zero amount."""
        # Arrange
        amount = 0
        type_raw = "지출"

        # Act
        result = _normalize_amount(amount, type_raw)

        # Assert
        assert result == 0


class TestIngestFile:
    """Test single file ingestion."""

    def test_ingest_file_success(self, temp_csv_base_dir, sample_xlsx_file):
        """Test successful ingestion of a single file."""
        # Act
        inserted, skipped, skipped_rows = ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert
        assert inserted == 3
        assert skipped == 0
        assert len(skipped_rows) == 0

        # Verify data in CSV partitions
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 3

    def test_ingest_file_creates_row_hash(self, temp_csv_base_dir, sample_xlsx_file):
        """Test that row_hash is generated for each transaction."""
        # Act
        ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        hashes = df["row_hash"].to_list()
        assert len(hashes) == 3
        assert all(len(h) == 16 for h in hashes)  # SHA256[:16] - optimized for token efficiency
        assert len(set(hashes)) == 3  # All unique

    def test_ingest_file_builds_datetime(self, temp_csv_base_dir, sample_xlsx_file):
        """Test that datetime field is constructed from date and time."""
        # Act
        ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        df = df.sort("date")
        datetimes = df["datetime"].to_list()
        assert datetimes[0] == "2025-10-27T19:24:00"
        assert datetimes[1] == "2025-10-28T08:30:00"
        assert datetimes[2] == "2025-10-29T12:45:00"

    def test_ingest_file_normalizes_amounts(self, temp_csv_base_dir, sample_xlsx_file):
        """Test that amounts are normalized based on type."""
        # Act
        ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        df = df.sort("date")

        # First row: 지출 (expense) should be negative
        assert df.row(0, named=True)["type_raw"] == "지출"
        assert df.row(0, named=True)["amount"] == -5000

        # Second row: 수입 (income) should be positive
        assert df.row(1, named=True)["type_raw"] == "수입"
        assert df.row(1, named=True)["amount"] == 3000000

        # Third row: 지출 (expense) should be negative
        assert df.row(2, named=True)["type_raw"] == "지출"
        assert df.row(2, named=True)["amount"] == -1500

    def test_ingest_file_idempotency_no_duplicates(self, temp_csv_base_dir, sample_xlsx_file):
        """Test that re-ingesting the same file does not create duplicates."""
        # Act - Ingest twice
        inserted1, skipped1, skipped_rows1 = ingest_file(sample_xlsx_file, temp_csv_base_dir)
        inserted2, skipped2, skipped_rows2 = ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert - First run inserts all
        assert inserted1 == 3
        assert skipped1 == 0

        # Second run skips all (deduplication by row_hash)
        assert inserted2 == 0
        assert skipped2 == 3

        # Verify total count is still 3
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 3

    def test_ingest_file_preserves_existing_on_duplicate(self, temp_csv_base_dir, temp_import_dir):
        """Test that existing data is preserved when duplicate is detected (CSV is append-only)."""
        # Arrange - Create initial file
        df1 = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "대분류": ["식비"],
                "중분류": ["카페"],
                "내용": ["스타벅스"],
                "메모": [""],
                "금액": [-5000],
                "화폐": ["KRW"],
                "결제수단": ["체크카드"],
            }
        )
        file1 = temp_import_dir / "data1.xlsx"
        write_banksalad_xlsx(df1, file1)

        # Ingest first time
        ingest_file(file1, temp_csv_base_dir)

        # Verify initial category
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert df.row(0, named=True)["major_raw"] == "식비"
        assert df.row(0, named=True)["minor_raw"] == "카페"

        # Arrange - Create second file with SAME transaction but DIFFERENT categories
        df2 = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "대분류": ["문화생활"],  # Changed
                "중분류": ["음료"],  # Changed
                "내용": ["스타벅스"],
                "메모": [""],
                "금액": [-5000],
                "화폐": ["KRW"],
                "결제수단": ["체크카드"],
            }
        )
        file2 = temp_import_dir / "data2.xlsx"
        write_banksalad_xlsx(df2, file2)

        # Act - Ingest second file
        inserted, skipped, skipped_rows = ingest_file(file2, temp_csv_base_dir)

        # Assert - Should be skipped (CSV is append-only, no updates)
        assert inserted == 0
        assert skipped == 1

        # Verify original categories were preserved (not overwritten)
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 1  # Still only one transaction
        assert df.row(0, named=True)["major_raw"] == "식비"
        assert df.row(0, named=True)["minor_raw"] == "카페"

    def test_ingest_file_source_tracking(self, temp_csv_base_dir, sample_xlsx_file):
        """Test that source file tracking fields are populated."""
        # Act
        ingest_file(sample_xlsx_file, temp_csv_base_dir)

        # Assert
        df = csv_partition.get_all_transactions(temp_csv_base_dir)

        for row in df.iter_rows(named=True):
            # file_id should be generated (format: YYMMDD_N or 8-char hash)
            assert "file_id" in row
            assert len(row["file_id"]) >= 8  # At least 8 chars
            assert row["source_row"] >= 2  # Excel rows start at 2 (after header)

    def test_ingest_file_missing_required_column(self, temp_csv_base_dir, temp_import_dir):
        """Test that file with missing required column raises error."""
        # Arrange - Create file missing 'time' column
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "결제수단": ["체크카드"],
            }
        )
        file_path = temp_import_dir / "invalid.xlsx"
        write_banksalad_xlsx(df, file_path)

        # Act & Assert - Should raise ValidationError for missing required column
        from finjuice.pipeline.validation import ValidationError

        with pytest.raises(ValidationError, match="필수 컬럼이 누락되었습니다"):
            ingest_file(file_path, temp_csv_base_dir)

    def test_ingest_file_empty_file(self, temp_csv_base_dir, temp_import_dir):
        """Test ingesting empty XLSX file returns zero rows silently."""
        schema = {
            "날짜": pl.Utf8,
            "시간": pl.Utf8,
            "타입": pl.Utf8,
            "내용": pl.Utf8,
            "금액": pl.Int64,
            "결제수단": pl.Utf8,
        }
        df = pl.DataFrame(schema=schema)
        file_path = temp_import_dir / "empty.xlsx"
        write_banksalad_xlsx(df, file_path)

        inserted, updated, skipped = ingest_file(file_path, temp_csv_base_dir)
        assert inserted == 0
        assert updated == 0
        assert skipped == []


class TestIngestAllFiles:
    """Test batch ingestion of multiple files."""

    def test_ingest_all_files_success(self, temp_csv_base_dir, temp_import_dir):
        """Test batch ingestion of multiple files."""
        # Arrange - Create two test files
        df1 = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "대분류": ["식비"],
                "중분류": ["카페"],
                "내용": ["스타벅스"],
                "메모": [""],
                "금액": [-5000],
                "화폐": ["KRW"],
                "결제수단": ["체크카드"],
            }
        )
        df2 = pl.DataFrame(
            {
                "날짜": ["2025-10-28"],
                "시간": ["08:30"],
                "타입": ["수입"],
                "대분류": ["급여"],
                "중분류": ["월급"],
                "내용": ["회사"],
                "메모": [""],
                "금액": [3000000],
                "화폐": ["KRW"],
                "결제수단": ["은행계좌"],
            }
        )

        file1 = temp_import_dir / "data1.xlsx"
        file2 = temp_import_dir / "data2.xlsx"
        write_banksalad_xlsx(df1, file1)
        write_banksalad_xlsx(df2, file2)

        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        assert summary["files"] == 2
        assert summary["inserted"] == 2
        assert summary["failed"] == 0

        # Verify CSV partitions
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 2

    def test_ingest_all_files_no_files(self, temp_csv_base_dir, temp_import_dir):
        """Test batch ingestion with no XLSX files."""
        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        assert summary["files"] == 0
        assert summary["inserted"] == 0
        assert summary["failed"] == 0

    def test_ingest_all_files_ignores_non_xlsx(self, temp_csv_base_dir, temp_import_dir):
        """Test that non-XLSX files are ignored."""
        # Arrange - Create some non-XLSX files
        (temp_import_dir / "readme.txt").write_text("test")
        (temp_import_dir / "data.csv").write_text("date,amount\n2025-10-27,-5000")

        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        assert summary["files"] == 0

    def test_ingest_all_files_handles_failure_gracefully(self, temp_csv_base_dir, temp_import_dir):
        """Test that failure in one file doesn't stop processing of others."""
        # Arrange - Create one valid file and one invalid file
        df_valid = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "화폐": ["KRW"],
                "결제수단": ["체크카드"],
            }
        )

        df_invalid = pl.DataFrame(
            {
                "날짜": ["2025-10-28"],
                # Missing required column 'time'
                "타입": ["지출"],
                "내용": ["카페"],
                "금액": [-3000],
            }
        )

        file_valid = temp_import_dir / "valid.xlsx"
        file_invalid = temp_import_dir / "invalid.xlsx"
        write_banksalad_xlsx(df_valid, file_valid)
        write_banksalad_xlsx(df_invalid, file_invalid)

        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        assert summary["files"] == 2
        assert summary["inserted"] == 1  # Only valid file inserted
        assert summary["failed"] == 1  # Invalid file failed

        # Verify only valid data in CSV partitions
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 1

    def test_ingest_all_files_cross_file_deduplication(self, temp_csv_base_dir, temp_import_dir):
        """Test that duplicates are detected across multiple files."""
        # Arrange - Create two files with overlapping data
        df1 = pl.DataFrame(
            {
                "날짜": ["2025-10-27", "2025-10-28"],
                "시간": ["19:24", "08:30"],
                "타입": ["지출", "수입"],
                "대분류": ["식비", "급여"],
                "중분류": ["카페", "월급"],
                "내용": ["스타벅스", "회사"],
                "메모": ["", ""],
                "금액": [-5000, 3000000],
                "화폐": ["KRW", "KRW"],
                "결제수단": ["체크카드", "은행계좌"],
            }
        )

        df2 = pl.DataFrame(
            {
                "날짜": ["2025-10-28", "2025-10-29"],  # 10-28 overlaps with df1
                "시간": ["08:30", "12:45"],
                "타입": ["수입", "지출"],
                "대분류": ["급여", "교통"],
                "중분류": ["월급", "지하철"],
                "내용": ["회사", "교통카드"],
                "메모": ["", ""],
                "금액": [3000000, -1500],
                "화폐": ["KRW", "KRW"],
                "결제수단": ["은행계좌", "교통카드"],
            }
        )

        file1 = temp_import_dir / "data1.xlsx"
        file2 = temp_import_dir / "data2.xlsx"
        write_banksalad_xlsx(df1, file1)
        write_banksalad_xlsx(df2, file2)

        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        # First file: 2 inserted
        # Second file: 1 skipped (duplicate), 1 inserted (new)
        assert summary["files"] == 2
        assert summary["inserted"] == 3  # Total unique transactions

        # Verify total count in CSV partitions
        df = csv_partition.get_all_transactions(temp_csv_base_dir)
        assert len(df) == 3  # Only 3 unique transactions
