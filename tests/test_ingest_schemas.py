"""
Tests for Column Schema Mapping module.

Tests schema detection, column mapping, and validation logic for Banksalad XLSX exports.
"""

import polars as pl
import pytest

from finjuice.pipeline.ingest.schemas import (
    BANKSALAD_SCHEMAS,
    detect_schema_version,
    map_columns,
)


class TestColumnSchema:
    """Test ColumnSchema dataclass."""

    def test_schema_structure(self):
        """Test that v1_2024 schema has expected structure."""
        # Arrange & Act
        schema = BANKSALAD_SCHEMAS["v1_2024"]

        # Assert
        assert schema.version == "v1_2024"
        assert isinstance(schema.date, list)
        assert isinstance(schema.time, list)
        assert isinstance(schema.type, list)
        assert isinstance(schema.merchant, list)
        assert isinstance(schema.amount, list)
        assert isinstance(schema.account, list)

    def test_schema_has_korean_variants(self):
        """Test that schema includes Korean column names."""
        # Arrange & Act
        schema = BANKSALAD_SCHEMAS["v1_2024"]

        # Assert
        assert "날짜" in schema.date
        assert "시간" in schema.time
        assert "타입" in schema.type
        assert "내용" in schema.merchant
        assert "금액" in schema.amount
        assert "결제수단" in schema.account

    def test_schema_has_english_variants(self):
        """Test that schema includes English column names."""
        # Arrange & Act
        schema = BANKSALAD_SCHEMAS["v1_2024"]

        # Assert
        assert "Date" in schema.date
        assert "Time" in schema.time
        assert "Type" in schema.type
        assert "Merchant" in schema.merchant
        assert "Amount" in schema.amount
        assert "Account" in schema.account


class TestDetectSchemaVersion:
    """Test schema version detection logic."""

    def test_detect_korean_columns(self):
        """Test detection with Korean column names."""
        # Arrange
        df_columns = [
            "날짜",
            "시간",
            "타입",
            "대분류",
            "중분류",
            "내용",
            "메모",
            "금액",
            "화폐",
            "결제수단",
        ]

        # Act
        detected_schema = detect_schema_version(df_columns)

        # Assert
        assert detected_schema.version == "v1_2024"

    def test_detect_english_columns(self):
        """Test detection with English column names."""
        # Arrange
        df_columns = [
            "Date",
            "Time",
            "Type",
            "Major Category",
            "Minor Category",
            "Merchant",
            "Memo",
            "Amount",
            "Currency",
            "Account",
        ]

        # Act
        detected_schema = detect_schema_version(df_columns)

        # Assert
        assert detected_schema.version == "v1_2024"

    def test_detect_mixed_columns(self):
        """Test detection with mixed Korean/English column names."""
        # Arrange
        df_columns = ["날짜", "Time", "타입", "Merchant", "금액", "Account"]

        # Act
        detected_schema = detect_schema_version(df_columns)

        # Assert
        assert detected_schema.version == "v1_2024"

    def test_detect_with_extra_columns(self):
        """Test detection ignores extra columns."""
        # Arrange
        df_columns = [
            "날짜",
            "시간",
            "타입",
            "내용",
            "금액",
            "결제수단",
            "ExtraColumn1",
            "ExtraColumn2",
        ]

        # Act
        detected_schema = detect_schema_version(df_columns)

        # Assert
        assert detected_schema.version == "v1_2024"

    def test_detect_partial_match_fallback(self):
        """Test fallback to v1_2024 when partial match."""
        # Arrange - Missing some optional fields, but has required fields
        df_columns = ["날짜", "금액", "결제수단", "UnknownColumn"]

        # Act
        detected_schema = detect_schema_version(df_columns)

        # Assert
        assert detected_schema.version == "v1_2024"


class TestMapColumns:
    """Test column mapping logic."""

    def test_map_korean_columns(self):
        """Test mapping Korean column names to standard names."""
        # Arrange
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "대분류": ["식비"],
                "중분류": ["카페"],
                "내용": ["스타벅스"],
                "메모": ["회의"],
                "금액": [-5000],
                "화폐": ["KRW"],
                "결제수단": ["체크카드"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "date" in mapped_df.columns
        assert "time" in mapped_df.columns
        assert "type" in mapped_df.columns
        assert "major_category" in mapped_df.columns
        assert "minor_category" in mapped_df.columns
        assert "merchant" in mapped_df.columns
        assert "memo" in mapped_df.columns
        assert "amount" in mapped_df.columns
        assert "currency" in mapped_df.columns
        assert "account" in mapped_df.columns

        # Verify data preserved
        assert mapped_df.row(0, named=True)["date"] == "2025-10-27"
        assert mapped_df.row(0, named=True)["amount"] == -5000

    def test_map_english_columns(self):
        """Test mapping English column names to standard names."""
        # Arrange
        df = pl.DataFrame(
            {
                "Date": ["2025-10-27"],
                "Time": ["19:24"],
                "Type": ["지출"],
                "Major Category": ["식비"],
                "Minor Category": ["카페"],
                "Merchant": ["스타벅스"],
                "Memo": ["회의"],
                "Amount": [-5000],
                "Currency": ["KRW"],
                "Account": ["체크카드"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "date" in mapped_df.columns
        assert "time" in mapped_df.columns
        assert "merchant" in mapped_df.columns
        assert "amount" in mapped_df.columns

    def test_map_mixed_columns(self):
        """Test mapping mixed Korean/English column names."""
        # Arrange
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "Time": ["19:24"],
                "타입": ["지출"],
                "Merchant": ["스타벅스"],
                "금액": [-5000],
                "Account": ["체크카드"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "date" in mapped_df.columns
        assert "time" in mapped_df.columns
        assert "type" in mapped_df.columns
        assert "merchant" in mapped_df.columns
        assert "amount" in mapped_df.columns
        assert "account" in mapped_df.columns

    def test_map_preserves_extra_columns(self):
        """Test that extra columns are preserved after mapping."""
        # Arrange
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "시간": ["19:24"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "결제수단": ["체크카드"],
                "ExtraColumn": ["ExtraValue"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "ExtraColumn" in mapped_df.columns
        assert mapped_df.row(0, named=True)["ExtraColumn"] == "ExtraValue"

    def test_map_missing_required_date(self):
        """Test that missing required field 'date' raises ValueError."""
        # Arrange
        df = pl.DataFrame(
            {
                "시간": ["19:24"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "결제수단": ["체크카드"],
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다:.*날짜"):
            map_columns(df)

    def test_map_missing_required_time(self):
        """Test that missing required field 'time' raises ValueError."""
        # Arrange
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "결제수단": ["체크카드"],
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다:.*시간"):
            map_columns(df)

    def test_map_missing_multiple_required(self):
        """Test that missing multiple required fields raises ValueError with all missing fields."""
        # Arrange
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],
                "금액": [-5000],
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다"):
            map_columns(df)

    def test_map_empty_dataframe(self):
        """Test mapping empty dataframe with valid columns."""
        # Arrange
        schema = {
            "날짜": pl.Utf8,
            "시간": pl.Utf8,
            "타입": pl.Utf8,
            "내용": pl.Utf8,
            "금액": pl.Int64,
            "결제수단": pl.Utf8,
        }
        df = pl.DataFrame(schema=schema)

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "date" in mapped_df.columns
        assert "time" in mapped_df.columns
        assert len(mapped_df) == 0

    def test_map_alternative_korean_variants(self):
        """Test mapping with alternative Korean column names."""
        # Arrange - Using variants like '거래일', '거래시간', '거래처'
        df = pl.DataFrame(
            {
                "거래일": ["2025-10-27"],
                "거래시간": ["19:24"],
                "유형": ["지출"],
                "거래처": ["스타벅스"],
                "거래금액": [-5000],
                "계좌/카드": ["체크카드"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        assert "date" in mapped_df.columns
        assert "time" in mapped_df.columns
        assert "type" in mapped_df.columns
        assert "merchant" in mapped_df.columns
        assert "amount" in mapped_df.columns
        assert "account" in mapped_df.columns

    def test_map_selects_first_matching_variant(self):
        """Test that mapping selects first matching variant when multiple variants exist."""
        # Arrange - DataFrame has multiple variants for the same field
        df = pl.DataFrame(
            {
                "날짜": ["2025-10-27"],  # First variant
                "거래일": ["2025-10-28"],  # Second variant (should be ignored)
                "시간": ["19:24"],
                "타입": ["지출"],
                "내용": ["스타벅스"],
                "금액": [-5000],
                "결제수단": ["체크카드"],
            }
        )

        # Act
        mapped_df = map_columns(df)

        # Assert
        # Should map to '날짜' (first variant in schema list)
        assert "date" in mapped_df.columns
        assert mapped_df.row(0, named=True)["date"] == "2025-10-27"
        # '거래일' should still exist as unmapped column
        assert "거래일" in mapped_df.columns
