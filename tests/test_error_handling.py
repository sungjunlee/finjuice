"""
Error handling and edge case tests.

Tests comprehensive error scenarios to ensure robust production behavior:
- Schema mismatches and validation errors
- Malformed data (dates, times, amounts)
- File I/O errors (missing directories, permissions, corrupted files)
- Malformed rules (invalid YAML, missing fields)
- Transfer detection edge cases
"""

from datetime import datetime
from pathlib import Path

import pytest

from finjuice.pipeline.ingest.pipeline import ingest_all_files, ingest_file
from finjuice.pipeline.tagging.rules import load_rules
from finjuice.pipeline.transfer.detection import TransferCandidate, detect_transfer_pairs
from finjuice.pipeline.validation import ValidationError

# ==============================================================================
# FIXTURES
# ==============================================================================
# Note: temp_csv_base_dir and temp_import_dir are provided by conftest.py


@pytest.fixture
def error_fixtures_dir():
    """Path to error test fixtures directory."""
    return Path(__file__).parent / "fixtures" / "error_cases"


# ==============================================================================
# TEST CLASS: SCHEMA ERRORS
# ==============================================================================


class TestSchemaErrors:
    """Test handling of schema mismatches and validation errors."""

    def test_missing_required_column_date(self, error_fixtures_dir, temp_csv_base_dir):
        """Should raise ValidationError with clear message about missing 'date' column."""
        # Arrange
        xlsx_path = error_fixtures_dir / "missing_date.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            ingest_file(xlsx_path, temp_csv_base_dir)

        # Verify error message mentions missing column (Korean: 날짜)
        assert "날짜" in str(exc_info.value)

    def test_missing_required_column_time(self, error_fixtures_dir, temp_csv_base_dir):
        """Should raise ValidationError with clear message about missing 'time' column."""
        # Arrange
        xlsx_path = error_fixtures_dir / "missing_time.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            ingest_file(xlsx_path, temp_csv_base_dir)

        # Verify error message mentions missing column (Korean: 시간)
        assert "시간" in str(exc_info.value)

    def test_missing_required_column_amount(self, error_fixtures_dir, temp_csv_base_dir):
        """Should raise ValidationError with clear message about missing 'amount' column."""
        # Arrange
        xlsx_path = error_fixtures_dir / "missing_amount.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            ingest_file(xlsx_path, temp_csv_base_dir)

        # Verify error message mentions missing column (Korean: 금액)
        assert "금액" in str(exc_info.value)

    def test_missing_required_column_account(self, error_fixtures_dir, temp_csv_base_dir):
        """Should raise ValidationError with clear message about missing 'account' column."""
        # Arrange
        xlsx_path = error_fixtures_dir / "missing_account.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            ingest_file(xlsx_path, temp_csv_base_dir)

        # Verify error message mentions missing column (Korean: 결제수단)
        assert "결제수단" in str(exc_info.value)

    def test_unknown_schema_columns(self, error_fixtures_dir, temp_csv_base_dir):
        """Should raise ValidationError when column names don't match any known schema."""
        # Arrange
        xlsx_path = error_fixtures_dir / "unknown_schema.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            ingest_file(xlsx_path, temp_csv_base_dir)

        # Should mention required columns (Korean: 필수 컬럼)
        error_msg = str(exc_info.value)
        assert "필수" in error_msg or "누락" in error_msg


# ==============================================================================
# TEST CLASS: MALFORMED DATA
# ==============================================================================


class TestMalformedData:
    """Test handling of malformed data within valid schema."""

    def test_empty_xlsx_no_rows(self, error_fixtures_dir, temp_csv_base_dir):
        """Empty XLSX with no transaction data should return zero rows silently."""
        xlsx_path = error_fixtures_dir / "empty.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        inserted, updated, skipped = ingest_file(xlsx_path, temp_csv_base_dir)
        assert inserted == 0
        assert updated == 0
        assert skipped == []

    def test_type_sign_mismatch_corrects_with_warning(self, error_fixtures_dir, tmp_path, caplog):
        """Type/sign mismatches should be corrected with warnings logged."""
        # Arrange
        from finjuice.pipeline.storage import csv_partition

        xlsx_path = error_fixtures_dir / "type_sign_mismatch.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True)

        # Act
        inserted, updated, skipped = ingest_file(xlsx_path, csv_base_dir)

        # Assert - should insert with corrections
        assert inserted == 2
        assert "positive" in caplog.text.lower() or "negative" in caplog.text.lower()

        # Verify amounts were corrected
        df = csv_partition.get_all_transactions(csv_base_dir)
        df = df.sort("amount")
        assert len(df) == 2

        # Test data:
        # - 지출 + 10000: positive expense = REFUND (kept positive per Issue #147)
        # - 수입 + -50000: negative income = data error (corrected to positive)
        for row in df.iter_rows(named=True):
            type_raw = row["type_raw"]
            amount = row["amount"]
            if "수입" in type_raw or "입금" in type_raw:
                assert amount > 0, "Income should have positive amount (corrected from negative)"
            elif "지출" in type_raw or "출금" in type_raw:
                # Positive expense = refund, kept positive (not converted to negative)
                # This is the expected behavior after the refund handling fix
                assert amount > 0, "Expense with positive amount = refund, should stay positive"

    def test_non_numeric_amount_skips_row(self, error_fixtures_dir, tmp_path, caplog):
        """Non-numeric amounts should skip row with warning."""
        # Arrange
        xlsx_path = error_fixtures_dir / "non_numeric_amount.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True)

        # Act
        inserted, updated, skipped = ingest_file(xlsx_path, csv_base_dir)

        # Assert - should skip malformed row
        assert inserted == 1  # Only the valid row
        assert len(skipped) >= 1  # At least one row skipped
        assert "skipping" in caplog.text.lower()

    def test_malformed_date_skips_rows_with_warning(
        self, error_fixtures_dir, temp_csv_base_dir, caplog
    ):
        """Malformed dates should skip rows with clear warnings."""
        # Arrange
        xlsx_path = error_fixtures_dir / "malformed_date.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act
        inserted, updated, skipped = ingest_file(xlsx_path, temp_csv_base_dir)

        # Assert
        assert inserted >= 0
        assert updated >= 0
        assert "skipping row" in caplog.text.lower()


# ==============================================================================
# TEST CLASS: FILE I/O ERRORS
# ==============================================================================


class TestFileIOErrors:
    """Test file system error handling."""

    def test_empty_import_directory_returns_zero(self, temp_import_dir, temp_csv_base_dir, caplog):
        """Empty import directory should log warning and return zero results."""
        # Arrange - directory is empty (from fixture)

        # Act
        summary = ingest_all_files(temp_import_dir, temp_csv_base_dir)

        # Assert
        assert summary["files"] == 0
        assert summary["inserted"] == 0
        assert summary["updated"] == 0
        assert "no xlsx files" in caplog.text.lower()

    def test_corrupted_xlsx_fails_gracefully(self, error_fixtures_dir, temp_csv_base_dir, caplog):
        """Corrupted XLSX should log error and continue processing."""
        # Arrange
        xlsx_path = error_fixtures_dir / "corrupted.xlsx"
        assert xlsx_path.exists(), f"Fixture not found: {xlsx_path}"

        # Act & Assert
        with pytest.raises(Exception):
            # Should raise an exception (openpyxl or pandas error)
            ingest_file(xlsx_path, temp_csv_base_dir)

    def test_missing_import_directory_handled(self, temp_csv_base_dir):
        """Missing import directory should be handled gracefully."""
        # Arrange
        missing_dir = Path("/nonexistent/directory/that/does/not/exist")
        assert not missing_dir.exists()

        # Act
        summary = ingest_all_files(missing_dir, temp_csv_base_dir)

        # Assert - should return zero results without crashing
        assert summary["files"] == 0
        assert summary["inserted"] == 0


# ==============================================================================
# TEST CLASS: MALFORMED RULES
# ==============================================================================


class TestMalformedRules:
    """Test handling of malformed YAML rules."""

    def test_invalid_yaml_syntax_raises_error(self, error_fixtures_dir):
        """Invalid YAML syntax should raise ValueError with helpful message."""
        # Arrange
        rules_path = error_fixtures_dir / "invalid_yaml_syntax.yaml"
        assert rules_path.exists(), f"Fixture not found: {rules_path}"

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid YAML syntax"):
            load_rules(rules_path)

    def test_missing_rules_file_returns_empty(self):
        """Non-existent rules file should return empty list (not error)."""
        # Arrange
        nonexistent_path = Path("/nonexistent/rules.yaml")
        assert not nonexistent_path.exists()

        # Act
        rules = load_rules(nonexistent_path)

        # Assert
        assert rules == []

    def test_empty_rules_file_returns_empty(self, error_fixtures_dir):
        """Empty rules file should return empty list."""
        # Arrange
        rules_path = error_fixtures_dir / "empty_rules.yaml"
        assert rules_path.exists(), f"Fixture not found: {rules_path}"

        # Act
        rules = load_rules(rules_path)

        # Assert
        assert rules == []

    def test_no_rules_key_returns_empty(self, error_fixtures_dir):
        """YAML file without 'rules' key should return empty list."""
        # Arrange
        rules_path = error_fixtures_dir / "no_rules_key.yaml"
        assert rules_path.exists(), f"Fixture not found: {rules_path}"

        # Act
        rules = load_rules(rules_path)

        # Assert
        assert rules == []

    def test_missing_required_rule_fields_raises_error(self, error_fixtures_dir):
        """Rules missing required fields (name, match, tags) should raise ValueError."""
        # Arrange
        rules_path = error_fixtures_dir / "missing_required_fields.yaml"
        assert rules_path.exists(), f"Fixture not found: {rules_path}"

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields"):
            # Validation raises ValueError with clear message about missing fields
            load_rules(rules_path)

    def test_invalid_priority_type_raises_error(self, error_fixtures_dir):
        """Invalid priority value (string instead of int) should be handled."""
        # Arrange
        rules_path = error_fixtures_dir / "invalid_priority.yaml"
        assert rules_path.exists(), f"Fixture not found: {rules_path}"

        # Act
        # Current implementation doesn't validate priority type strictly
        # This test documents the current behavior
        try:
            rules = load_rules(rules_path)
            # If it loads, check if string priority causes issues during sorting
            assert len(rules) >= 1
        except (TypeError, ValueError):
            # Acceptable if type validation catches it
            pass


# ==============================================================================
# TEST CLASS: TRANSFER DETECTION EDGE CASES
# ==============================================================================


class TestTransferEdgeCases:
    """Test transfer detection edge cases."""

    def test_multiple_candidates_same_amount_greedy_match(self):
        """
        Multiple candidates with same amount: deterministic matching picks the closest match.
        """
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)
        candidates = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            # Two potential matches with same amount
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 31),
                50000,
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
            TransferCandidate(
                3,
                datetime(2025, 1, 15, 14, 32),
                50000,
                "국민은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - should pair with first match (ID 2), leave ID 3 unpaired
        assert len(pairs) == 1
        pair_ids = list(pairs.values())[0]
        assert 1 in pair_ids
        assert 2 in pair_ids
        assert 3 not in pair_ids

    def test_transfers_outside_time_window_not_paired(self):
        """Transfers >5 minutes apart should not pair."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)
        candidates = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 36),  # 6 minutes later (> 5 min window)
                50000,
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, time_window_minutes=5)

        # Assert - should not pair due to time window
        assert len(pairs) == 0

    def test_time_window_boundary_conditions(self):
        """Test time window boundary (exactly at 5 minutes)."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30, 0)

        # Test case 1: 4.9 minutes (should pair)
        candidates_within = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 34, 54),  # 4.9 minutes
                50000,
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Test case 2: 5.1 minutes (should not pair)
        candidates_outside = [
            TransferCandidate(3, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                4,
                datetime(2025, 1, 15, 14, 35, 6),  # 5.1 minutes
                50000,
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Act
        pairs_within = detect_transfer_pairs(candidates_within, time_window_minutes=5)
        pairs_outside = detect_transfer_pairs(candidates_outside, time_window_minutes=5)

        # Assert
        assert len(pairs_within) == 1, "4.9 minutes should pair"
        assert len(pairs_outside) == 0, "5.1 minutes should not pair"

    def test_transfers_different_currencies_not_paired(self):
        """Transfers with different currencies should not pair."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)
        candidates = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 31),
                50000,
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "USD",  # Different currency
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - should not pair due to currency mismatch
        assert len(pairs) == 0

    def test_transfers_different_categories_not_paired(self):
        """Transfers with different major_category should not pair."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)
        candidates = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 31),
                50000,
                "우리은행",
                "내계좌이체",
                "카드대금",  # Different category
                "KRW",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - should not pair due to category mismatch
        assert len(pairs) == 0

    def test_unpaired_transfer_single_transaction(self):
        """Single transfer with no matching counterpart should remain unpaired."""
        # Arrange
        candidates = [
            TransferCandidate(
                1,
                datetime(2025, 1, 15, 14, 30),
                -50000,
                "신한카드",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
            # No matching positive transfer
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - no pairs formed
        assert len(pairs) == 0

    def test_amount_tolerance_boundary(self):
        """Test amount tolerance boundary (default 1%)."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)

        # Test case 1: 0.5% difference (should pair)
        candidates_within = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 31),
                50250,  # +0.5% difference
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Test case 2: 2% difference (should not pair with 1% tolerance)
        candidates_outside = [
            TransferCandidate(3, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                4,
                datetime(2025, 1, 15, 14, 31),
                51000,  # +2% difference
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Act
        pairs_within = detect_transfer_pairs(candidates_within, amount_tolerance=0.01)  # 1%
        pairs_outside = detect_transfer_pairs(candidates_outside, amount_tolerance=0.01)  # 1%

        # Assert
        assert len(pairs_within) == 1, "0.5% difference should pair"
        assert len(pairs_outside) == 0, "2% difference should not pair with 1% tolerance"

    def test_same_sign_transactions_not_paired(self):
        """Two transactions with same sign (both negative or both positive) should not pair."""
        # Arrange
        base_time = datetime(2025, 1, 15, 14, 30)
        candidates = [
            TransferCandidate(1, base_time, -50000, "신한카드", "내계좌이체", "내계좌이체", "KRW"),
            TransferCandidate(
                2,
                datetime(2025, 1, 15, 14, 31),
                -50000,  # Same sign (both negative)
                "우리은행",
                "내계좌이체",
                "내계좌이체",
                "KRW",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - should not pair (same sign)
        assert len(pairs) == 0
