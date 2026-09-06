"""
Polars-optimized CSV report generation (Issue #91 - Task 1.5).

This module provides 2-5x faster report generation using Polars for:
- Monthly spend aggregation
- Tag-based spending analysis
- Category-based spending analysis (v3 schema, no duplicate counting)
- Account-level summaries
- Transfer audit logs

All functions maintain identical API and output format to pandas version.

CSV load/write helpers live in
:mod:`finjuice.pipeline.export.reports_polars_helpers`, the shared
export-error translation lives in
:mod:`finjuice.pipeline.export.reports_polars_errors`, and report-frame
construction / export glue lives in
:mod:`finjuice.pipeline.export.reports_polars_cluster`; all are re-exported
here so existing callers can keep importing from this module.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from finjuice.pipeline.export.reports_polars_cluster import (
    POLARS_AVAILABLE,  # noqa: F401 — re-exported for existing reports_polars imports
    _aggregate_by_account,
    _aggregate_by_category,
    _aggregate_by_tag,
    _aggregate_monthly_spend,
    _aggregate_transfers,
    _load_transfer_source_df,
    _require_polars,
    _write_report_output,
)
from finjuice.pipeline.export.reports_polars_errors import _translate_export_errors
from finjuice.pipeline.export.reports_polars_helpers import (
    UTF8_BOM,  # noqa: F401 — re-exported for existing reports_polars imports
    _load_report_source_df,
    _write_csv_with_bom,  # noqa: F401 — re-exported for existing reports_polars imports
)

if TYPE_CHECKING:
    import polars as pl

logger = logging.getLogger(__name__)


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
    _require_polars()
    with _translate_export_errors("monthly_spend"):
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate for monthly spend")
            return 0

        monthly = _aggregate_monthly_spend(df)
        return _write_report_output(monthly, output_path, "monthly_spend")


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
    _require_polars()
    with _translate_export_errors("by_tag"):
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by tag")
            return 0

        by_tag = _aggregate_by_tag(df)
        if by_tag is None:
            return 0
        return _write_report_output(by_tag, output_path, "by_tag")


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
    _require_polars()
    with _translate_export_errors("by_category"):
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by category")
            return 0

        by_category = _aggregate_by_category(df)
        if by_category is None:
            return 0
        return _write_report_output(by_category, output_path, "by_category")


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
    _require_polars()
    with _translate_export_errors("by_account"):
        df = _load_report_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to aggregate by account")
            return 0

        by_account = _aggregate_by_account(df)
        return _write_report_output(by_account, output_path, "by_account")


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
    _require_polars()
    with _translate_export_errors("transfers"):
        df = _load_transfer_source_df(csv_base_dir, source_df)

        if df.is_empty():
            logger.warning("No transactions to filter for transfers")
            return 0

        df_transfers = _aggregate_transfers(df)
        if df_transfers is None:
            return 0
        return _write_report_output(df_transfers, output_path, "transfers")
