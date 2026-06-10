"""
Tests for Row Hash & Deduplication module.

Tests hash calculation, deduplication logic, and source tracking for transaction ingestion.
"""

import sys

import pytest

from finjuice.pipeline.ingest.deduplication import build_source_id, calculate_row_hash


class TestCalculateRowHash:
    """Test row hash calculation for deduplication."""

    def test_hash_success_with_all_fields(self):
        """Test hash calculation with complete transaction data."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act
        hash_result = calculate_row_hash(row)

        # Assert
        assert isinstance(hash_result, str)
        assert len(hash_result) == 16  # SHA256[:16] - optimized for token efficiency

    def test_hash_consistency(self):
        """Test that same data produces same hash (deterministic)."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act
        hash1 = calculate_row_hash(row)
        hash2 = calculate_row_hash(row)

        # Assert
        assert hash1 == hash2

    def test_hash_uniqueness_different_amount(self):
        """Test that different amounts produce different hashes."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }
        row2 = {**row1, "amount": -6000}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 != hash2

    def test_hash_uniqueness_different_merchant(self):
        """Test that different merchants produce different hashes."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }
        row2 = {**row1, "merchant": "카페베네"}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 != hash2

    def test_hash_uniqueness_different_date(self):
        """Test that different dates produce different hashes."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }
        row2 = {**row1, "date": "2025-10-28"}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 != hash2

    def test_hash_excludes_memo(self):
        """Test that memo field is excluded from hash (same hash despite different memo)."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
            "memo": "회의",
        }
        row2 = {**row1, "memo": "개인"}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 == hash2

    def test_hash_excludes_major_category(self):
        """Test that major_category is excluded from hash."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
            "major_category": "식비",
        }
        row2 = {**row1, "major_category": "문화생활"}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 == hash2

    def test_hash_excludes_minor_category(self):
        """Test that minor_category is excluded from hash."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
            "minor_category": "카페",
        }
        row2 = {**row1, "minor_category": "음료"}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 == hash2

    def test_hash_missing_date_raises_error(self):
        """Test that missing date field raises ValueError."""
        # Arrange
        row = {
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields.*date"):
            calculate_row_hash(row)

    def test_hash_missing_time_raises_error(self):
        """Test that missing time field raises ValueError."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields.*time"):
            calculate_row_hash(row)

    def test_hash_missing_amount_raises_error(self):
        """Test that missing amount field raises ValueError."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields.*amount"):
            calculate_row_hash(row)

    def test_hash_missing_multiple_fields_raises_error(self):
        """Test that missing multiple fields raises ValueError with all missing fields."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "merchant": "스타벅스",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields"):
            calculate_row_hash(row)

    def test_hash_empty_string_date_raises_error(self):
        """Test that empty string for date raises ValueError."""
        # Arrange
        row = {
            "date": "",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields.*date"):
            calculate_row_hash(row)

    def test_hash_none_value_raises_error(self):
        """Test that None value for required field raises ValueError."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": None,
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="missing required fields.*merchant"):
            calculate_row_hash(row)

    def test_hash_amount_sign_matters(self):
        """Test that amount sign affects hash (negative vs positive)."""
        # Arrange
        row1 = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }
        row2 = {**row1, "amount": 5000}

        # Act
        hash1 = calculate_row_hash(row1)
        hash2 = calculate_row_hash(row2)

        # Assert
        assert hash1 != hash2

    def test_hash_amount_zero_is_valid(self):
        """Test that zero amount is valid (not treated as empty)."""
        # Arrange
        row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": 0,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act & Assert - Should not raise
        hash_result = calculate_row_hash(row)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 16

    def test_hash_with_whitespace_in_merchant(self):
        """Test that whitespace is normalized in hash calculation."""
        # Arrange - Two rows with same data, but one has leading/trailing whitespace
        row_without_whitespace = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        row_with_whitespace = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "  스타벅스  ",  # Whitespace from Excel formatting
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        # Act
        hash_without = calculate_row_hash(row_without_whitespace)
        hash_with = calculate_row_hash(row_with_whitespace)

        # Assert - Both should produce the same hash (whitespace normalized)
        assert hash_without == hash_with
        assert len(hash_without) == 16

    def test_hash_collision_probability_realistic_dataset(self):
        """
        Test that 10-char hash provides sufficient uniqueness for realistic dataset.

        With 10 hex chars (40 bits), we have ~1 trillion combinations.
        For 100K transactions (lifetime of personal finance data), collision probability < 0.001%.
        This test verifies uniqueness across a sample of 10K transactions.
        """
        # Arrange - Generate 10K unique transactions
        base_row = {
            "date": "2025-10-27",
            "time": "19:24",
            "type": "지출",
            "merchant": "스타벅스",
            "amount": -5000,
            "currency": "KRW",
            "account": "체크카드",
        }

        hashes = set()
        collision_count = 0

        # Act - Generate hashes for 10K unique transactions (vary by amount)
        for i in range(10000):
            row = {**base_row, "amount": -5000 - i}
            hash_value = calculate_row_hash(row)

            if hash_value in hashes:
                collision_count += 1
            hashes.add(hash_value)

        # Assert - No collisions expected in 10K transactions
        assert collision_count == 0, f"Found {collision_count} collisions in 10K transactions"
        assert len(hashes) == 10000


class TestBuildSourceId:
    """Test source ID building for traceability."""

    def test_build_source_id_success(self):
        """Test building source ID from file path and row number."""
        # Arrange
        file_path = "d:/finance/imports/2024-10-27~2025-10-27.xlsx"
        row_num = 42

        # Act
        source_id = build_source_id(file_path, row_num)

        # Assert
        assert source_id == "2024-10-27~2025-10-27.xlsx:row42"

    def test_build_source_id_with_relative_path(self):
        """Test building source ID with relative path."""
        # Arrange
        file_path = "imports/banksalad.xlsx"
        row_num = 1

        # Act
        source_id = build_source_id(file_path, row_num)

        # Assert
        assert source_id == "banksalad.xlsx:row1"

    @pytest.mark.skipif(
        not sys.platform.startswith("win"), reason="Windows path parsing only works on Windows"
    )
    def test_build_source_id_with_windows_path(self):
        """Test building source ID with Windows path.

        Note: On POSIX systems (macOS, Linux), pathlib.Path treats backslash
        as a regular character, not a path separator. This test is only valid
        on Windows where backslash is the path separator.
        """
        # Arrange
        file_path = r"C:\Users\User\finance\imports\data.xlsx"
        row_num = 100

        # Act
        source_id = build_source_id(file_path, row_num)

        # Assert
        assert source_id == "data.xlsx:row100"

    def test_build_source_id_with_zero_row(self):
        """Test building source ID with row 0 (header row)."""
        # Arrange
        file_path = "data.xlsx"
        row_num = 0

        # Act
        source_id = build_source_id(file_path, row_num)

        # Assert
        assert source_id == "data.xlsx:row0"

    def test_build_source_id_format(self):
        """Test that source ID format is consistent: filename:rowN."""
        # Arrange
        file_path = "/path/to/file.xlsx"
        row_num = 999

        # Act
        source_id = build_source_id(file_path, row_num)

        # Assert
        assert source_id.startswith("file.xlsx:row")
        assert source_id.endswith("999")
        assert ":" in source_id
