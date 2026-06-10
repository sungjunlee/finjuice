"""Edge case tests for export modules to improve coverage.

Tests exception handling, error conditions, and edge cases in:
- export.master module (CSV partition source)
- export.reports module (CSV partition source)
"""

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import polars as pl
import pytest

from finjuice.pipeline.export.master import export_master_xlsx
from finjuice.pipeline.export.reports import (
    export_by_account,
    export_by_tag,
    export_monthly_spend,
    export_transfers,
)
from finjuice.pipeline.export.spreadsheet_security import neutralize_spreadsheet_formula
from finjuice.pipeline.storage import csv_partition


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(1,1)", "'+SUM(1,1)"),
        ('-HYPERLINK("https://example.invalid")', '\'-HYPERLINK("https://example.invalid")'),
        ("@SUM(1,1)", "'@SUM(1,1)"),
        ("\t=1+1", "'\t=1+1"),
        ("\n+SUM(1,1)", "'\n+SUM(1,1)"),
        ("\r@SUM(1,1)", "'\r@SUM(1,1)"),
        ("스타벅스", "스타벅스"),
    ],
)
def test_neutralize_spreadsheet_formula_string_edges(value: str, expected: str) -> None:
    """Spreadsheet export strings that could become formulas are prefixed only at export."""
    # Act
    result = neutralize_spreadsheet_formula(value)

    # Assert
    assert result == expected


@pytest.mark.parametrize("value", [-5000, 0, 1234.5, None])
def test_neutralize_spreadsheet_formula_preserves_non_strings(value: object) -> None:
    """Numeric export values must stay numeric instead of becoming spreadsheet text."""
    # Act
    result = neutralize_spreadsheet_formula(value)

    # Assert
    assert result == value


@pytest.fixture
def temp_csv_base_dir(tmp_path: Path):  # type: ignore[misc]
    """Create a temporary CSV partitions directory."""
    csv_dir = tmp_path / "transactions"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


@pytest.fixture
def sample_transactions() -> list[Dict[str, Any]]:
    """Sample transaction data for edge case testing."""
    return [
        {
            "row_hash": "a" * 64,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "스타벅스",
            "memo_raw": "커피",
            "amount": -5000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "스타벅스",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["카페", "커피"],
            "tags_ai": [],
            "tags_final": ["카페", "커피"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]


# ============================================================================
# Master Export Edge Cases
# ============================================================================


class TestMasterExportEdgeCases:
    """Test edge cases in master XLSX export."""

    def test_export_master_xlsx_nonexistent_csv_dir(self, tmp_path: Path) -> None:
        """Test export with nonexistent CSV partition directory."""
        # Arrange
        nonexistent_dir = tmp_path / "nonexistent"
        output_path = tmp_path / "master.xlsx"

        # Act
        row_count = export_master_xlsx(nonexistent_dir, output_path)

        # Assert - should return 0 and not create file
        assert row_count == 0
        assert not output_path.exists()

    def test_export_master_xlsx_empty_partitions(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test export with existing but empty partition directories."""
        # Arrange - Create empty year/month directories
        (temp_csv_base_dir / "2025" / "01").mkdir(parents=True, exist_ok=True)
        output_path = tmp_path / "master.xlsx"

        # Act
        row_count = export_master_xlsx(temp_csv_base_dir, output_path)

        # Assert
        assert row_count == 0
        assert not output_path.exists()

    @patch("polars.DataFrame.write_excel")
    def test_export_master_xlsx_polars_write_error(
        self,
        mock_write_excel,
        temp_csv_base_dir: Path,
        sample_transactions: list[Dict[str, Any]],
        tmp_path: Path,
    ) -> None:
        """Test export handles polars write errors."""
        # Arrange
        df = pl.DataFrame(sample_transactions)
        csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)
        output_path = tmp_path / "master.xlsx"

        # Mock polars error
        mock_write_excel.side_effect = Exception("Polars write error")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            export_master_xlsx(temp_csv_base_dir, output_path)

        assert "Polars write error" in str(exc_info.value)

    def test_export_master_xlsx_invalid_output_path(
        self, temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
    ) -> None:
        """Test export handles read-only output paths."""
        # Arrange
        df = pl.DataFrame(sample_transactions)
        csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

        # Create a read-only directory to trigger PermissionError
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only for all

        output_path = readonly_dir / "master.xlsx"

        # Act & Assert - Should raise RuntimeError wrapping PermissionError
        with pytest.raises(RuntimeError, match="Failed to export master XLSX"):
            export_master_xlsx(temp_csv_base_dir, output_path)

        # Cleanup: restore write permissions for test cleanup
        readonly_dir.chmod(0o755)


# ============================================================================
# Reports Export Edge Cases
# ============================================================================


class TestReportsExportEdgeCases:
    """Test edge cases in report exports."""

    def test_export_monthly_spend_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test monthly_spend with nonexistent CSV directory."""
        # Arrange
        nonexistent_dir = tmp_path / "nonexistent"
        output_path = tmp_path / "monthly.csv"

        # Act
        row_count = export_monthly_spend(nonexistent_dir, output_path)

        # Assert
        assert row_count == 0
        assert not output_path.exists()

    def test_export_by_tag_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test by_tag with nonexistent CSV directory."""
        # Arrange
        nonexistent_dir = tmp_path / "nonexistent"
        output_path = tmp_path / "by_tag.csv"

        # Act
        row_count = export_by_tag(nonexistent_dir, output_path)

        # Assert
        assert row_count == 0
        assert not output_path.exists()

    def test_export_by_account_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test by_account with nonexistent CSV directory."""
        # Arrange
        nonexistent_dir = tmp_path / "nonexistent"
        output_path = tmp_path / "by_account.csv"

        # Act
        row_count = export_by_account(nonexistent_dir, output_path)

        # Assert
        assert row_count == 0
        assert not output_path.exists()

    def test_export_transfers_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test transfers with nonexistent CSV directory."""
        # Arrange
        nonexistent_dir = tmp_path / "nonexistent"
        output_path = tmp_path / "transfers.csv"

        # Act
        row_count = export_transfers(nonexistent_dir, output_path)

        # Assert
        assert row_count == 0
        assert not output_path.exists()
