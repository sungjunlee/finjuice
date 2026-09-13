"""finjuice CLI: ``show`` command for displaying transactions with filters.

Extracted from ``cli/commands/init.py`` as part of Batch 3a of Epic #707.
Human rendering lives in :mod:`finjuice.pipeline.cli.commands.show_rendering`.
The Polars data-loading helpers remain inline for now; the optional
extraction into a dedicated use-case layer (#700 deeper rework) is a
follow-on.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import polars as pl
import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.show_rendering import _render_show_table
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.cli.report_filters import apply_report_filters, load_cli_report_filters
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def _load_latest_month(csv_base_dir: Path) -> tuple[Optional[pl.DataFrame], Optional[str]]:
    """Load transactions from the most recent partition.

    Args:
        csv_base_dir: Base directory containing year/month partitions

    Returns:
        (DataFrame, month_label) or (None, None) if no data
    """
    from finjuice.pipeline.storage.csv_transactions import read_month

    # Find latest partition
    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None, None

    latest = partitions[-1]

    # Extract year/month from path
    parts = latest.parts
    year = int(parts[-3])
    month = int(parts[-2])
    month_label = f"{year:04d}-{month:02d}"

    df = read_month(csv_base_dir, year, month)
    return df, month_label


def _load_all_partitions(csv_base_dir: Path) -> tuple[Optional[pl.DataFrame], int]:
    """Load transactions from every available partition."""
    from finjuice.pipeline.storage.csv_transactions import get_all_transactions

    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None, 0

    return get_all_transactions(csv_base_dir), len(partitions)


def _load_sqlite_month(database: Path, year: int, month: int) -> Optional[pl.DataFrame]:
    """Load one month from the SQLite repository read adapter.

    Returns ``None`` when the repository holds no rows for that month, which
    matches the CSV behavior for a missing partition. (A CSV partition that
    exists but is empty still renders an empty table; the repository has no
    empty-month equivalent.)
    """
    from finjuice.pipeline.storage.sqlite.read_compat import read_month_frame

    df = read_month_frame(database, year, month)
    return None if df.is_empty() else df


def _load_sqlite_all(database: Path) -> tuple[Optional[pl.DataFrame], int]:
    """Load every transaction from the SQLite repository read adapter."""
    from finjuice.pipeline.storage.sqlite.read_compat import (
        distinct_month_count,
        read_transactions_frame,
    )

    df = read_transactions_frame(database)
    if df.is_empty():
        return None, 0
    return df, distinct_month_count(df)


def _load_sqlite_latest_month(database: Path) -> tuple[Optional[pl.DataFrame], Optional[str]]:
    """Load the newest month from the SQLite repository read adapter."""
    from finjuice.pipeline.storage.sqlite.read_compat import (
        filter_month_frame,
        latest_month_label,
        read_transactions_frame,
    )

    df = read_transactions_frame(database)
    month_label = latest_month_label(df)
    if month_label is None:
        return None, None
    year_int, mon_int = (int(part) for part in month_label.split("-"))
    return filter_month_frame(df, year_int, mon_int), month_label


def _load_month_frame(
    config: Any,
    sqlite_database: Optional[Path],
    month: str,
    *,
    json_output: bool,
) -> tuple[Optional[pl.DataFrame], str]:
    """Load one specific month from SQLite or CSV partitions (same contract)."""
    year_str, mon_str = month.split("-")
    year_int, mon_int = int(year_str), int(mon_str)
    if sqlite_database is not None:
        df = _load_sqlite_month(sqlite_database, year_int, mon_int)
    else:
        csv_path = config.csv_base_dir / year_str / mon_str / "transactions.csv"
        if not csv_path.exists():
            df = None
        else:
            from finjuice.pipeline.storage.csv_transactions import read_month

            df = read_month(config.csv_base_dir, year_int, mon_int)
    if df is None:
        emit_error(
            f"No data for {month}",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            json_output=json_output,
            command="show",
        )
    return df, f"Transactions ({month})"


def _load_bare_frame(
    config: Any,
    sqlite_database: Optional[Path],
    filters: tuple[bool, Optional[str], Optional[str]],
    *,
    json_output: bool,
) -> tuple[Optional[pl.DataFrame], str, str]:
    """Load the bare-`show` scope (all partitions or latest month).

    ``filters`` is ``(untagged, tag, merchant)`` — only their presence
    decides the scan scope; the actual filtering stays in the command.
    """
    untagged, tag, merchant = filters
    search_all_partitions = untagged or tag is not None or merchant is not None
    if not search_all_partitions:
        # Latest month
        if sqlite_database is not None:
            df, month_label = _load_sqlite_latest_month(sqlite_database)
        else:
            df, month_label = _load_latest_month(config.csv_base_dir)
        if df is None:
            emit_error(
                "No transaction data found",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=json_output,
                command="show",
            )
        assert month_label is not None, "month_label should not be None when df is not None"
        return df, f"Transactions ({month_label})", ""
    if sqlite_database is not None:
        df, partition_count = _load_sqlite_all(sqlite_database)
    else:
        df, partition_count = _load_all_partitions(config.csv_base_dir)
    if df is None:
        emit_error(
            "No transaction data found",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            json_output=json_output,
            command="show",
        )
    partition_word = "partition" if partition_count == 1 else "partitions"
    return df, "Transactions", f" across {partition_count} {partition_word}"


def show_command(
    ctx: typer.Context,
    month: Optional[str] = typer.Option(None, "--month", help="Filter by month (YYYY-MM)"),
    untagged: bool = typer.Option(False, "--untagged", help="Show only untagged transactions"),
    tag: Optional[str] = typer.Option(
        None,
        "--tag",
        help=(
            "Filter by tag (exact match; scans all partitions when --month is omitted). "
            'Quote tags that contain spaces or brackets, e.g. --tag "[테스트]LLM서비스".'
        ),
    ),
    merchant: Optional[str] = typer.Option(
        None, "--merchant", help="Filter by merchant (case-insensitive)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of transactions to show"),
    cursor: str = typer.Option("0", "--cursor", help="Opaque pagination cursor"),
    max_bytes: int = typer.Option(
        output.DEFAULT_MAX_BYTES,
        "--max-bytes",
        help="Maximum serialized JSON response size before truncating rows",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show transactions with optional filters.

    Displays transactions in a formatted table with options to filter by:
    - Month (YYYY-MM format)
    - Untagged status
    - Specific tag
    - Merchant name

    Scope:
        - Bare `show` (no filters): latest month only (bounded output).
        - Any of --tag/--untagged/--merchant without --month: scans all partitions.
        - --month X: scoped to that month only, regardless of other filters.

    Examples:
        # Show latest 20 transactions (latest month only)
        finjuice show

        # Show October 2024 transactions
        finjuice show --month 2024-10

        # Show untagged transactions (across all partitions)
        finjuice show --untagged --limit 50

        # Show specific tag (across all partitions)
        finjuice show --tag 카페 --limit 30

        # Quote tags with brackets/spaces
        finjuice show --tag "[테스트]LLM서비스"

        # Combine month + tag to scope to a single month
        finjuice show --month 2025-04 --tag 카페

        # Show specific merchant
        finjuice show --merchant 스타벅스
    """
    config = get_config(ctx)
    limit, cursor_offset, max_bytes = output.validate_pagination_args(
        limit,
        cursor,
        max_bytes,
        json_output=json_output,
        command="show",
    )

    try:
        # Load data. When FINJUICE_SQLITE_GENERATION configures a published
        # repository, reads go through the SQLite read adapter (#436); the
        # frame contract is identical to the CSV partition read path.
        from finjuice.pipeline.storage.sqlite.read_compat import resolve_generation_database

        sqlite_database = resolve_generation_database()
        filters_applied = 0
        scope_hint = ""
        table_title = "Transactions"
        if month:
            df, table_title = _load_month_frame(
                config, sqlite_database, month, json_output=json_output
            )
        else:
            df, table_title, scope_hint = _load_bare_frame(
                config,
                sqlite_database,
                (untagged, tag, merchant),
                json_output=json_output,
            )

        report_filters = load_cli_report_filters(
            ctx,
            config,
            command="show",
            json_output=json_output,
        )
        assert df is not None, "df should not be None after data-loading guards"
        df, filters_applied = apply_report_filters(df, report_filters)

        # Apply filters
        if untagged:
            # tags_final is a List type, check for empty list or null
            df = df.filter(
                (pl.col("tags_final").list.len() == 0) | (pl.col("tags_final").is_null())
            )

        if tag:
            # tags_final is a List type, check if it contains the tag
            df = df.filter(pl.col("tags_final").list.contains(tag))

        if merchant:
            df = df.filter(pl.col("merchant_raw").str.to_lowercase().str.contains(merchant.lower()))

        total_count_before_limit = len(df)

        # Sort by datetime descending and apply offset-backed pagination.
        df = df.sort("datetime", descending=True).slice(cursor_offset, limit)
        pagination = output.build_offset_pagination(
            limit=limit,
            cursor_offset=cursor_offset,
            total_estimate=total_count_before_limit,
            fetched_count=len(df),
        )

        rows = df.to_dicts()
        if json_output:
            from finjuice.pipeline.tagging.manual import strip_sentinels_from_row

            payload = output.truncate_rows_to_max_bytes(
                {
                    "rows": [strip_sentinels_from_row(r) for r in rows],
                    "row_count": len(rows),
                    "total_matches": total_count_before_limit,
                },
                pagination=pagination,
                max_bytes=max_bytes,
                command="show",
                meta_extras={"filters_applied": filters_applied},
            )
            output.emit(
                payload,
                True,
                lambda _: None,
                command="show",
                meta_extras={"filters_applied": filters_applied},
            )
            return

        _render_show_table(
            df,
            table_title=table_title,
            scope_hint=scope_hint,
            pagination=pagination,
        )

    except typer.Exit:
        raise
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Failed to show transactions: {e}", exc_info=True)
        emit_error(
            f"Failed to show transactions: {e}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="show",
        )
