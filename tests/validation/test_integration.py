"""
Integration tests for validation with ingest pipeline.

Tests that validation is properly integrated into the ingestion workflow.
"""

import polars as pl
import pytest
import xlsxwriter

from finjuice.pipeline.ingest.pipeline import ingest_file


def _write_multi_sheet_xlsx(path, sheets: dict[str, pl.DataFrame]) -> None:
    """Write multiple DataFrames to different sheets in an Excel file.

    Args:
        path: Output file path
        sheets: Dict mapping sheet names to Polars DataFrames
    """
    workbook = xlsxwriter.Workbook(str(path))
    for sheet_name, df in sheets.items():
        worksheet = workbook.add_worksheet(sheet_name)
        # Write headers
        for col_idx, col_name in enumerate(df.columns):
            worksheet.write(0, col_idx, col_name)
        # Write data rows
        for row_idx, row in enumerate(df.iter_rows(named=True)):
            for col_idx, col_name in enumerate(df.columns):
                value = row[col_name]
                if value is not None:
                    worksheet.write(row_idx + 1, col_idx, value)
    workbook.close()


class TestIngestValidation:
    """Test validation integration with ingest pipeline."""

    def test_ingest_rejects_invalid_schema(self, tmp_path):
        """Ingest should reject files with invalid schema."""
        # Create XLSX with wrong columns in sheet 1 (Banksalad format)
        df = pl.DataFrame(
            {
                "wrong_col1": [1, 2, 3],
                "wrong_col2": ["a", "b", "c"],
            }
        )

        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_path = imports_dir / "invalid.xlsx"

        # Write to both sheets to match Banksalad format
        _write_multi_sheet_xlsx(
            xlsx_path,
            {
                "Sheet0": pl.DataFrame({"dummy": [1]}),
                "Sheet1": df,
            },
        )

        csv_dir = tmp_path / "transactions"
        csv_dir.mkdir()

        # Should raise ValueError with missing column info
        with pytest.raises(ValueError) as exc_info:
            ingest_file(xlsx_path, csv_dir)

        error_msg = str(exc_info.value)
        assert "필수 컬럼이 누락" in error_msg

    # NOTE: Full end-to-end tests with valid schemas are covered in existing integration tests
    # This test focuses on validation error handling only
