"""
CSV report generation from CSV partitions (Polars-only).

This module exports transaction data aggregated from CSV partitions
to CSV files for analysis and review.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Final

if TYPE_CHECKING:
    import polars as pl

from finjuice.pipeline.constants import REPORTS_COUNT, STANDARD_CSV_REPORTS

from . import reports_polars

logger = logging.getLogger(__name__)


def export_monthly_spend(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export monthly spending summary to CSV (Polars-only).

    Aggregates spending by month from CSV partitions. Transfers are excluded from totals.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of rows exported

    Example:
        >>> from pathlib import Path
        >>> row_count = export_monthly_spend(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports/monthly_spend.csv")
        ... )
        >>> print(f"Exported {row_count} months")
    """
    return reports_polars.export_monthly_spend_polars(csv_base_dir, output_path, source_df)


def export_by_tag(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export spending by tag to CSV (Polars-only).

    Explodes tags_final array and aggregates spending by tag.
    Transfers are excluded from totals.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of tag rows exported

    Example:
        >>> from pathlib import Path
        >>> row_count = export_by_tag(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports/by_tag.csv")
        ... )
        >>> print(f"Exported {row_count} unique tags")
    """
    return reports_polars.export_by_tag_polars(csv_base_dir, output_path, source_df)


def export_by_category(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export spending by category to CSV (v3 schema, Polars-only).

    Aggregates spending by category_final field. Unlike by_tag, this
    provides accurate totals without duplicate counting (one transaction
    has exactly one category).

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of category rows exported

    Example:
        >>> from pathlib import Path
        >>> row_count = export_by_category(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports/by_category.csv")
        ... )
        >>> print(f"Exported {row_count} unique categories")
    """
    return reports_polars.export_by_category_polars(csv_base_dir, output_path, source_df)


def export_by_account(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export net spending by account/card to CSV (Polars-only).

    Aggregates spending by account from CSV partitions.
    Transfers are excluded from totals.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of account rows exported

    Example:
        >>> from pathlib import Path
        >>> row_count = export_by_account(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports/by_account.csv")
        ... )
        >>> print(f"Exported {row_count} accounts")
    """
    return reports_polars.export_by_account_polars(csv_base_dir, output_path, source_df)


def export_transfers(
    csv_base_dir: Path,
    output_path: Path,
    source_df: "pl.DataFrame | None" = None,
) -> int:
    """
    Export transfer audit log to CSV (Polars-only).

    Filters confirmed transfer pairs from CSV partitions.
    Includes transfer_group_id and transfer candidate/confirmed flags for audit.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output CSV file

    Returns:
        int: Number of transfer rows exported

    Example:
        >>> from pathlib import Path
        >>> row_count = export_transfers(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports/transfers.csv")
        ... )
        >>> print(f"Exported {row_count} transfer transactions")
    """
    return reports_polars.export_transfers_polars(csv_base_dir, output_path, source_df)


_ReportExporter = Callable[[Path, Path, Any], int]

_REPORT_EXPORTERS: Final[dict[str, _ReportExporter]] = {
    "monthly_spend": export_monthly_spend,
    "by_category": export_by_category,
    "by_tag": export_by_tag,
    "by_account": export_by_account,
    "transfers": export_transfers,
}


def generate_all_reports(
    csv_base_dir: Path,
    reports_dir: Path,
    source_df: "pl.DataFrame | None" = None,
) -> Dict[str, int | str]:
    """
    Generate all CSV reports in one call.

    Creates the reports directory if it doesn't exist and exports
    all standard reports. Continues processing even if one report
    fails, logging errors individually.

    Args:
        csv_base_dir: Base directory for CSV partitions
        reports_dir: Directory path for output CSV files

    Returns:
        Dict with summary:
            - reports: Number of reports generated (0-REPORTS_COUNT)
            - output_dir: Path to reports directory
            - monthly_spend: Row count (or 0 if failed)
            - by_category: Row count (or 0 if failed)
            - by_tag: Row count (or 0 if failed)
            - by_account: Row count (or 0 if failed)
            - transfers: Row count (or 0 if failed)

    Example:
        >>> from pathlib import Path
        >>> summary = generate_all_reports(
        ...     Path("data/transactions"),
        ...     Path("data/exports/reports")
        ... )
        >>> print(f"Generated {summary['reports']} reports")
        >>> print(f"Monthly data: {summary['monthly_spend']} months")
    """
    # Ensure reports directory exists
    reports_dir.mkdir(parents=True, exist_ok=True)

    summary_report: Dict[str, int | str] = {
        "reports": 0,
        "output_dir": str(reports_dir),
        **{report_key: 0 for report_key, _filename in STANDARD_CSV_REPORTS},
    }

    reports_count = 0
    for report_key, filename in STANDARD_CSV_REPORTS:
        try:
            count = _REPORT_EXPORTERS[report_key](csv_base_dir, reports_dir / filename, source_df)
            summary_report[report_key] = count
            reports_count += 1
        except RuntimeError as e:
            # Expected errors from export function (already logged there)
            logger.error(f"Failed to generate {report_key} report: {e}")
        except (OSError, ValueError) as e:
            logger.error("Unexpected error in %s report (%s)", report_key, type(e).__name__)

    summary_report["reports"] = reports_count

    report_counts = ", ".join(
        f"{report_key}={summary_report[report_key]}"
        for report_key, _filename in STANDARD_CSV_REPORTS
    )
    logger.info(
        f"Generated {summary_report['reports']}/{REPORTS_COUNT} reports in {reports_dir}: "
        f"{report_counts}"
    )

    return summary_report
