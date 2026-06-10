"""finjuice CLI: ``show`` command for displaying transactions with filters.

Extracted from ``cli/commands/init.py`` as part of Batch 3a of Epic #707.
The Polars data-loading helpers remain inline for now; the optional
extraction into a dedicated use-case layer (#700 deeper rework) is a
follow-on.
"""

import logging
from pathlib import Path
from typing import Optional

import polars as pl
import typer
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, emit_error
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
        # Load data
        df: Optional[pl.DataFrame]
        filters_applied = 0
        scope_hint = ""
        table_title = "Transactions"
        if month:
            # Specific month
            year_str, mon_str = month.split("-")
            year_int, mon_int = int(year_str), int(mon_str)
            csv_path = config.csv_base_dir / year_str / mon_str / "transactions.csv"
            if not csv_path.exists():
                emit_error(
                    f"No data for {month}",
                    error_code=ErrorCode.NO_DATA,
                    exit_code=ExitCode.NO_DATA,
                    json_output=json_output,
                    command="show",
                )
            from finjuice.pipeline.storage.csv_transactions import read_month

            df = read_month(config.csv_base_dir, year_int, mon_int)
            table_title = f"Transactions ({month})"
        else:
            search_all_partitions = untagged or tag is not None or merchant is not None
            if search_all_partitions:
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
                scope_hint = f" across {partition_count} {partition_word}"
            else:
                # Latest month
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
                month = month_label
                table_title = f"Transactions ({month})"

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

        if len(df) == 0:
            typer.echo("📝 No transactions match the filters.")
            return

        # Create Rich table
        table = Table(title=table_title)
        table.add_column("Date", style="cyan")
        table.add_column("Merchant", style="yellow")
        table.add_column("Amount", justify="right", style="green")
        table.add_column("Tags", style="blue")
        table.add_column("Account", style="magenta")

        for row in df.iter_rows(named=True):
            # Format amount with Korean won
            amount = row["amount"]
            amount_str = f"₩{abs(amount):,.0f}"
            if amount < 0:
                amount_str = f"-{amount_str}"

            # Truncate merchant name
            merchant_display = row.get("merchant_raw") or "N/A"
            if len(merchant_display) > 30:
                merchant_display = merchant_display[:27] + "..."

            # tags_final is now a List type from Polars schema
            tags = row.get("tags_final")
            if tags and isinstance(tags, list) and len(tags) > 0:
                tags_display = ", ".join(str(t) for t in tags)
            else:
                tags_display = "-"

            # Truncate account
            account = row.get("account") or "N/A"
            if len(account) > 15:
                account = account[:12] + "..."

            table.add_row(
                row["date"],
                merchant_display,
                amount_str,
                tags_display,
                account,
            )

        console.print(table)

        # Summary
        total = len(df)
        total_amount = df["amount"].sum()
        typer.echo(f"\n📊 Showing {total} transactions{scope_hint}")
        typer.echo(f"💰 Total: ₩{abs(total_amount):,.0f}")
        output.render_pagination_footer(total, pagination)

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
