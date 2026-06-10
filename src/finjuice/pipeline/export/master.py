"""
Master XLSX export for consolidated transaction data (Polars-only).

This module exports all transactions from CSV partitions to a single Excel file
with all fields including original data, normalized fields, tagging, and
transfer tracking information.
"""

import json
import logging
from pathlib import Path

import polars as pl

from finjuice.pipeline.export.spreadsheet_security import neutralize_spreadsheet_strings
from finjuice.pipeline.storage import csv_partition

logger = logging.getLogger(__name__)

# Master XLSX is a full-schema audit artifact. It intentionally exports every
# transaction CSV column, including v3 category/tag/file metadata, in storage
# order; there are no master-specific exclusions.
MASTER_EXPORT_COLUMNS = tuple(csv_partition.CSV_COLUMNS)
TAG_EXPORT_COLUMNS = ("tags_rule", "tags_ai", "tags_manual", "tags_final")


def export_master_xlsx(csv_base_dir: Path, output_path: Path) -> int:
    """
    Export all transactions to master XLSX file.

    Exports the complete transaction dataset in the CSV storage schema order.
    Tag arrays are converted to comma-separated strings for Excel readability.
    Transactions are sorted by date and time in descending order (most recent
    first).

    Args:
        csv_base_dir: Base directory for CSV partitions (e.g., data/transactions/)
        output_path: Path to output XLSX file (e.g., master_20251031.xlsx)

    Returns:
        int: Number of transactions exported

    Example:
        >>> from pathlib import Path
        >>> count = export_master_xlsx(
        ...     Path("data/transactions"),
        ...     Path("data/exports/master_20251031.xlsx")
        ... )
        >>> print(f"Exported {count} transactions")
    """
    try:
        # Load all transactions from CSV partitions
        df = csv_partition.get_all_transactions(csv_base_dir)
        row_count = len(df)

        if row_count == 0:
            logger.warning("No transactions to export")
            return 0

        df = _align_to_master_schema(df)

        # Convert list/JSON tag columns to comma-separated strings for Excel readability
        for col in TAG_EXPORT_COLUMNS:
            if col in df.columns:
                df = df.with_columns(
                    pl.col(col).map_elements(_convert_list_to_csv, return_dtype=pl.Utf8).alias(col)
                )

        # Sort by date and time descending (most recent first)
        df = df.sort(["date", "time"], descending=True)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to XLSX (Polars write_excel, uses xlsxwriter)
        export_df = neutralize_spreadsheet_strings(df)
        export_df.write_excel(output_path, worksheet="Transactions")

        logger.info("Exported master XLSX: %s transactions", row_count)
        return row_count

    except (PermissionError, OSError, IOError) as e:
        # File system errors - expected during export
        logger.error("Cannot write master XLSX (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export master XLSX: {e}") from e
    except (ValueError, KeyError) as e:
        # Data validation errors - expected from invalid DataFrame
        logger.error(f"Invalid data structure for export: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed during export: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(f"Polars error during master export: {type(e).__name__}: {e}", exc_info=True)
        raise RuntimeError(f"Data processing failed during export: {e}") from e
    except Exception as e:
        if "Permission denied" in str(e) or "FileCreateError" in type(e).__name__:
            logger.error("Cannot write master XLSX (%s)", type(e).__name__)
            raise RuntimeError(f"Failed to export master XLSX: {e}") from e
        logger.error(
            f"Unexpected error during master export: {type(e).__name__}: {e}", exc_info=True
        )
        raise


def _align_to_master_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Return ``df`` with exactly the transaction CSV schema columns."""
    missing_columns = [col for col in MASTER_EXPORT_COLUMNS if col not in df.columns]
    if missing_columns:
        df = df.with_columns(
            [
                pl.lit(None).cast(csv_partition.POLARS_SCHEMA.get(col, pl.Utf8)).alias(col)
                for col in missing_columns
            ]
        )

    return df.select(list(MASTER_EXPORT_COLUMNS))


def _convert_list_to_csv(tag_value: list[str] | str | pl.Series | None) -> str:
    """
    Convert Python list, Polars Series, or JSON string to comma-separated string.

    Args:
        tag_value: Python list (e.g., ['tag1', 'tag2']),
                   Polars Series (from map_elements on List column),
                   or JSON string (e.g., '["tag1", "tag2"]')

    Returns:
        str: Comma-separated string (e.g., "tag1, tag2")
             Empty string if input is None, empty list, or empty string

    Example:
        >>> _convert_list_to_csv(['카페', '커피'])
        '카페, 커피'
        >>> _convert_list_to_csv('["카페", "커피"]')
        '카페, 커피'
        >>> _convert_list_to_csv([])
        ''
        >>> _convert_list_to_csv(None)
        ''
    """
    # Handle None case
    if tag_value is None:
        return ""

    # Handle Polars Series (from map_elements on List column)
    if isinstance(tag_value, pl.Series):
        items = tag_value.to_list()
        if len(items) == 0:
            return ""
        return ", ".join(str(tag) for tag in items)

    # If it's a string, try to parse as JSON
    if isinstance(tag_value, str):
        # Handle empty string or empty JSON array
        if tag_value == "" or tag_value == "[]":
            return ""
        try:
            parsed = json.loads(tag_value)
            if isinstance(parsed, list):
                if len(parsed) == 0:
                    return ""
                return ", ".join(str(tag) for tag in parsed)
            return tag_value  # Return as-is if not a list
        except (json.JSONDecodeError, TypeError):
            return tag_value  # Return as-is if not valid JSON

    # Handle list case
    if isinstance(tag_value, list):
        if len(tag_value) == 0:
            return ""
        return ", ".join(str(tag) for tag in tag_value)

    # Default: return empty string for unexpected types
    return ""
