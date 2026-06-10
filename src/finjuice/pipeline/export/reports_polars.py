"""
Polars-optimized CSV report generation (Issue #91 - Task 1.5).

This module provides 2-5x faster report generation using Polars for:
- Monthly spend aggregation
- Tag-based spending analysis
- Category-based spending analysis (v3 schema, no duplicate counting)
- Account-level summaries
- Transfer audit logs

All functions maintain identical API and output format to pandas version.
"""

import logging
from pathlib import Path

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

from finjuice.pipeline.export.spreadsheet_security import neutralize_spreadsheet_strings
from finjuice.pipeline.filters import exclude_transfers_for, only_transfers

logger = logging.getLogger(__name__)

# UTF-8 BOM bytes for Excel compatibility
UTF8_BOM = b"\xef\xbb\xbf"


def _write_csv_with_bom(df: "pl.DataFrame", output_path: Path) -> None:
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
    source_df: "pl.DataFrame | None" = None,
) -> "pl.DataFrame":
    """Resolve the source DataFrame for report generation."""
    if source_df is not None:
        return source_df

    from finjuice.pipeline.storage import csv_transactions

    return csv_transactions.get_all_transactions(csv_base_dir)


def export_monthly_spend_polars(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export monthly spending summary using Polars (2-3x faster).

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of rows exported
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    try:
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate for monthly spend")
            return 0

        # Extract month from date (YYYY-MM format)
        df = df.with_columns(pl.col("date").str.slice(0, 7).alias("month"))

        # Filter: type_norm='expense' and exclude internal transfers
        df_expense = df.filter((pl.col("type_norm") == "expense") & exclude_transfers_for(df))

        # Group by month and sum amounts
        monthly = (
            df_expense.group_by("month")
            .agg(pl.col("amount").sum().round(0).alias("total_spend"))
            .sort("month", descending=True)
        )

        row_count = len(monthly)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to CSV with UTF-8 BOM for Excel compatibility
        _write_csv_with_bom(monthly, output_path)

        logger.info("Exported monthly_spend: %s rows", row_count)
        return row_count

    except (PermissionError, OSError) as e:
        logger.error("Cannot write monthly_spend report (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export monthly_spend report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for monthly_spend aggregation: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for monthly_spend: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(
            f"Polars error in monthly_spend export: {type(e).__name__}: {e}", exc_info=True
        )
        raise RuntimeError(f"Polars computation failed for monthly_spend: {e}") from e


def export_by_tag_polars(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export spending by tag using Polars (3-5x faster for list operations).

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of tag rows exported
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    try:
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by tag")
            return 0

        # Filter: exclude transfers AND type_norm=expense (exclude income and transfers)
        df_filtered = df.filter(exclude_transfers_for(df) & (pl.col("type_norm") == "expense"))

        # Explode tags_final array (each tag becomes a separate row)
        # Polars explode is much faster than pandas
        df_exploded = df_filtered.explode("tags_final")

        # Filter out rows with empty tags
        df_exploded = df_exploded.filter(
            pl.col("tags_final").is_not_null() & (pl.col("tags_final") != "")
        )

        if df_exploded.is_empty():
            logger.warning("No tags found in transactions")
            return 0

        # Group by tag and sum amounts
        by_tag = (
            df_exploded.group_by("tags_final")
            .agg(pl.col("amount").sum().round(0).alias("total"))
            .rename({"tags_final": "tag"})
            .sort("total", descending=False)  # Smallest expenses first
        )

        row_count = len(by_tag)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to CSV with UTF-8 BOM for Excel compatibility
        _write_csv_with_bom(by_tag, output_path)

        logger.info("Exported by_tag: %s rows", row_count)
        return row_count

    except (PermissionError, OSError) as e:
        logger.error("Cannot write by_tag report (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export by_tag report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for by_tag aggregation: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for by_tag: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(f"Polars error in by_tag export: {type(e).__name__}: {e}", exc_info=True)
        raise RuntimeError(f"Polars computation failed for by_tag: {e}") from e


def export_by_category_polars(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export spending by category using Polars (v3 schema - no duplicate counting).

    Unlike by_tag which can double-count (one transaction -> multiple tags),
    by_category uses category_final (single value per transaction) for accurate
    aggregation.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of category rows exported
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    try:
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by category")
            return 0

        # Validate v3 schema - category_final is required for this report
        if "category_final" not in df.columns:
            logger.error(
                "category_final column not found - data may be v2 schema. "
                "Run migration: python scripts/migrate_schema_v3.py --execute"
            )
            raise ValueError(
                "category_final column not found. Data may be v2 schema. "
                "Run: python scripts/migrate_schema_v3.py --execute"
            )

        # Filter: exclude transfers AND type_norm=expense (exclude income and transfers)
        df_filtered = df.filter(exclude_transfers_for(df) & (pl.col("type_norm") == "expense"))

        if df_filtered.is_empty():
            logger.warning("No expense transactions found")
            return 0

        # Group by category_final (single category per transaction = no duplicate counting)
        by_category = (
            df_filtered.group_by("category_final")
            .agg(
                [
                    pl.col("amount").sum().round(0).alias("total"),
                    pl.col("amount").count().alias("count"),
                ]
            )
            .rename({"category_final": "category"})
            .sort("total", descending=False)  # Largest expenses first (negative)
        )

        row_count = len(by_category)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to CSV with UTF-8 BOM for Excel compatibility
        _write_csv_with_bom(by_category, output_path)

        logger.info("Exported by_category: %s rows", row_count)
        return row_count

    except (PermissionError, OSError) as e:
        logger.error("Cannot write by_category report (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export by_category report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for by_category aggregation: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for by_category: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(f"Polars error in by_category export: {type(e).__name__}: {e}", exc_info=True)
        raise RuntimeError(f"Polars computation failed for by_category: {e}") from e


def export_by_account_polars(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export net spending by account using Polars (2-3x faster).

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of account rows exported
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    try:
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by account")
            return 0

        # Filter: exclude internal transfers
        df_non_transfer = df.filter(exclude_transfers_for(df))

        # Group by account and sum amounts
        by_account = (
            df_non_transfer.group_by("account")
            .agg(pl.col("amount").sum().round(0).alias("net_total"))
            .sort("net_total", descending=False)  # Largest expenses first (negative)
        )

        row_count = len(by_account)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to CSV with UTF-8 BOM for Excel compatibility
        _write_csv_with_bom(by_account, output_path)

        logger.info("Exported by_account: %s rows", row_count)
        return row_count

    except (PermissionError, OSError) as e:
        logger.error("Cannot write by_account report (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export by_account report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for by_account aggregation: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for by_account: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(f"Polars error in by_account export: {type(e).__name__}: {e}", exc_info=True)
        raise RuntimeError(f"Polars computation failed for by_account: {e}") from e


def export_transfers_polars(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export transfer audit log using Polars (2-3x faster).

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of transfer rows exported
    """
    if not POLARS_AVAILABLE or pl is None:
        raise RuntimeError("Polars is not available. Install with: pip install polars")

    try:
        columns = [
            "datetime",
            "amount",
            "account",
            "counterparty",
            "memo_raw",
            "transfer_group_id",
            "is_transfer_candidate",
            "is_transfer",
        ]
        if source_df is None:
            from finjuice.pipeline.storage import csv_transactions

            df = csv_transactions.get_all_transactions(csv_base_dir, columns=columns)
        else:
            df = source_df.select([column for column in columns if column in source_df.columns])

        if df.is_empty():
            logger.warning("No transactions to filter for transfers")
            return 0

        if "is_transfer_candidate" not in df.columns:
            df = df.with_columns(
                pl.col("is_transfer")
                .cast(pl.Int64, strict=False)
                .fill_null(0)
                .alias("is_transfer_candidate")
            )

        # Export only confirmed transfer pairs.
        df_transfers = df.filter(only_transfers())

        if df_transfers.is_empty():
            logger.info("No paired transfers to export")
            return 0

        # Sort by datetime descending (most recent first)
        df_transfers = df_transfers.sort("datetime", descending=True)

        row_count = len(df_transfers)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export to CSV with UTF-8 BOM for Excel compatibility
        _write_csv_with_bom(df_transfers, output_path)

        logger.info("Exported transfers: %s rows", row_count)
        return row_count

    except (PermissionError, OSError) as e:
        logger.error("Cannot write transfers report (%s)", type(e).__name__)
        raise RuntimeError(f"Failed to export transfers report: {e}") from e
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid data for transfers report: {e}", exc_info=True)
        raise RuntimeError(f"Data validation failed for transfers: {e}") from e
    except pl.exceptions.PolarsError as e:
        logger.error(f"Polars error in transfers export: {type(e).__name__}: {e}", exc_info=True)
        raise RuntimeError(f"Polars computation failed for transfers: {e}") from e
