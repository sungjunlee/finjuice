"""
Tests for amount validation warnings (Issue #91).

Tests that unusual amounts (too large or too small) generate appropriate
warning logs during ingestion, without causing hard failures.
"""

import logging

from finjuice.pipeline.constants import (
    MAX_REASONABLE_AMOUNT_KRW,
    MIN_REASONABLE_AMOUNT_KRW,
)
from finjuice.pipeline.ingest._normalize import _normalize_amount


class TestAmountValidationWarnings:
    """Test amount range validation warnings."""

    def test_normal_amount_no_warning(self, caplog):
        """Test that normal amounts do not generate warnings."""
        # Arrange
        normal_amounts = [
            (-5000, "지출"),  # Small expense
            (-1_000_000, "지출"),  # Medium expense
            (-100_000_000, "지출"),  # Large expense (100M)
            (3_000_000, "수입"),  # Salary income
            (-500_000_000, "이체"),  # Large transfer (still within bounds)
        ]

        # Act & Assert
        with caplog.at_level(logging.WARNING):
            for amount, type_raw in normal_amounts:
                result = _normalize_amount(amount, type_raw, row_idx=1)
                assert result is not None
                # Check no "비정상적으로" warning in logs
                assert "비정상적으로" not in caplog.text

    def test_large_amount_warning(self, caplog):
        """Test that amounts exceeding MAX_REASONABLE_AMOUNT_KRW generate warnings."""
        # Arrange
        large_amount = MAX_REASONABLE_AMOUNT_KRW + 1  # Just over 999M
        very_large_amount = 999_999_999_999  # ~1 trillion

        # Act & Assert
        with caplog.at_level(logging.WARNING):
            # Test large expense
            result1 = _normalize_amount(-large_amount, "지출", row_idx=10)
            assert result1 == -large_amount
            assert "비정상적으로 큰 금액" in caplog.text
            assert "row 10" in caplog.text

            caplog.clear()

            # Test very large income
            result2 = _normalize_amount(very_large_amount, "수입", row_idx=20)
            assert result2 == very_large_amount
            assert "비정상적으로 큰 금액" in caplog.text
            assert "row 20" in caplog.text

    def test_small_amount_warning(self, caplog):
        """Test that amounts below MIN_REASONABLE_AMOUNT_KRW generate warnings."""
        # Arrange
        small_amount = MIN_REASONABLE_AMOUNT_KRW / 2  # Half of minimum (0.005)
        tiny_amount = 0.001  # Very small

        # Act & Assert
        with caplog.at_level(logging.WARNING):
            # Test small expense
            result1 = _normalize_amount(-small_amount, "지출", row_idx=5)
            assert result1 == -small_amount
            assert "비정상적으로 작은 금액" in caplog.text
            assert "row 5" in caplog.text

            caplog.clear()

            # Test tiny income
            result2 = _normalize_amount(tiny_amount, "수입", row_idx=15)
            assert result2 == tiny_amount
            assert "비정상적으로 작은 금액" in caplog.text

    def test_zero_amount_no_small_warning(self, caplog):
        """Test that zero amount does NOT trigger small amount warning.

        Zero amounts may indicate cancelled transactions or data quality issues,
        but they should not trigger the "too small" warning (that's for 0 < amount < MIN).
        """
        # Arrange
        zero_amount = 0.0

        # Act
        with caplog.at_level(logging.WARNING):
            result = _normalize_amount(zero_amount, "지출", row_idx=1)

        # Assert
        assert result == 0.0
        # Should NOT warn about "비정상적으로 작은 금액" for zero
        assert "비정상적으로 작은" not in caplog.text

    def test_negative_amounts_validated_by_absolute_value(self, caplog):
        """Test that negative amounts are validated by absolute value."""
        # Arrange
        large_negative = -(MAX_REASONABLE_AMOUNT_KRW + 1_000_000)  # -1 billion

        # Act
        with caplog.at_level(logging.WARNING):
            result = _normalize_amount(large_negative, "지출", row_idx=100)

        # Assert
        assert result == large_negative
        assert "비정상적으로 큰 금액" in caplog.text
        assert "row 100" in caplog.text

    def test_boundary_values(self, caplog):
        """Test exact boundary values for MAX and MIN amounts."""
        # Arrange & Act & Assert

        # Exactly at MAX - no warning
        with caplog.at_level(logging.WARNING):
            caplog.clear()
            result_max = _normalize_amount(-MAX_REASONABLE_AMOUNT_KRW, "지출")
            assert result_max == -MAX_REASONABLE_AMOUNT_KRW
            assert "비정상적으로 큰" not in caplog.text

        # Exactly at MIN - no warning
        with caplog.at_level(logging.WARNING):
            caplog.clear()
            result_min = _normalize_amount(MIN_REASONABLE_AMOUNT_KRW, "수입")
            assert result_min == MIN_REASONABLE_AMOUNT_KRW
            assert "비정상적으로 작은" not in caplog.text

        # Just above MAX - warning
        with caplog.at_level(logging.WARNING):
            caplog.clear()
            _ = _normalize_amount(MAX_REASONABLE_AMOUNT_KRW + 0.01, "수입")
            assert "비정상적으로 큰 금액" in caplog.text

        # Just below MIN (but not zero) - warning
        with caplog.at_level(logging.WARNING):
            caplog.clear()
            _ = _normalize_amount(MIN_REASONABLE_AMOUNT_KRW - 0.001, "수입")
            assert "비정상적으로 작은 금액" in caplog.text

    def test_warning_does_not_change_amount(self, caplog):
        """Test that warning logs do not affect the returned amount."""
        # Arrange
        large_expense = -2_000_000_000  # 2 billion
        tiny_income = 0.001

        # Act
        with caplog.at_level(logging.WARNING):
            result_large = _normalize_amount(large_expense, "지출", row_idx=1)
            result_tiny = _normalize_amount(tiny_income, "수입", row_idx=2)

        # Assert - amounts should be returned as-is (after sign normalization)
        assert result_large == large_expense
        assert result_tiny == tiny_income

    def test_transfer_type_also_validated(self, caplog):
        """Test that transfer transactions are also validated for unusual amounts."""
        # Arrange
        large_transfer = 5_000_000_000  # 5 billion outgoing transfer

        # Act
        with caplog.at_level(logging.WARNING):
            result = _normalize_amount(large_transfer, "이체", row_idx=50)

        # Assert
        assert result == large_transfer
        assert "비정상적으로 큰 금액" in caplog.text
        assert "row 50" in caplog.text


class TestAmountValidationConstants:
    """Test that amount validation constants are properly defined."""

    def test_max_amount_constant_value(self):
        """Test MAX_REASONABLE_AMOUNT_KRW is 999 million."""
        assert MAX_REASONABLE_AMOUNT_KRW == 999_000_000

    def test_min_amount_constant_value(self):
        """Test MIN_REASONABLE_AMOUNT_KRW is 0.01."""
        assert MIN_REASONABLE_AMOUNT_KRW == 0.01

    def test_constants_relationship(self):
        """Test that MAX is much larger than MIN."""
        assert MAX_REASONABLE_AMOUNT_KRW > MIN_REASONABLE_AMOUNT_KRW
        assert MAX_REASONABLE_AMOUNT_KRW / MIN_REASONABLE_AMOUNT_KRW > 1_000_000
