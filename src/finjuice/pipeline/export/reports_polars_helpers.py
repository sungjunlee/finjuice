"""CSV load/write helpers for Polars report generation.

Owns UTF-8 BOM CSV writing and source DataFrame resolution. Public report
export functions stay in :mod:`finjuice.pipeline.export.reports_polars`,
which re-exports these names so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from finjuice.pipeline.export.spreadsheet_security import neutralize_spreadsheet_strings

if TYPE_CHECKING:
    import polars as pl

# UTF-8 BOM bytes for Excel compatibility
UTF8_BOM = b"\xef\xbb\xbf"


def _write_csv_with_bom(df: pl.DataFrame, output_path: Path) -> None:
    """
    Write Polars DataFrame to CSV with UTF-8 BOM for Korean Excel compatibility.

    Polars write_csv() doesn't support utf-8-sig encoding like pandas,
    so we manually prepend the BOM bytes.

    Args:
        df: Polars DataFrame to write
        output_path: Path to output CSV file
    """
    # Get CSV content as bytes
    export_df = neutralize_spreadsheet_strings(df)
    csv_bytes = export_df.write_csv(separator=",").encode("utf-8")

    # Write BOM + CSV content
    with open(output_path, "wb") as f:
        f.write(UTF8_BOM)
        f.write(csv_bytes)


def _load_report_source_df(
    csv_base_dir: Path,
    source_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Resolve the source DataFrame for report generation."""
    if source_df is not None:
        return source_df

    from finjuice.pipeline.storage import csv_transactions

    return csv_transactions.get_all_transactions(csv_base_dir)
