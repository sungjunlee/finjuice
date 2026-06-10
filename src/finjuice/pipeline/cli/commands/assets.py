"""Raw asset snapshot CLI commands.

Provides commands for viewing imported snapshot rows directly:
- status: Quick overview (total value, accounts, positions)
- show: Detailed holdings table
"""

import logging
from pathlib import Path
from typing import Any, Optional

import polars as pl
import typer
from rich.table import Table

from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit,
    emit_error,
    info,
    section,
    success,
    table_summary,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.networth import (
    discover_snapshot_months,
    load_latest_snapshot_partition,
    load_snapshot_partition,
)

logger = logging.getLogger(__name__)

assets_app = typer.Typer(
    name="assets",
    help="View raw asset snapshot rows and per-position holdings",
)


def _format_krw(amount: float) -> str:
    """Format amount as KRW."""
    return f"₩{abs(amount):,.0f}"


def _build_status_result(
    snapshots_dir: Path,
) -> dict[str, Any]:
    """Build asset status data."""
    months = discover_snapshot_months(snapshots_dir)
    if not months:
        return {"has_data": False}

    df, month_label = load_latest_snapshot_partition(snapshots_dir)
    if df is None or df.is_empty():
        return {"has_data": False}

    # Find latest snapshot date within the partition
    latest_date = df.select(pl.col("snapshot_date").max()).to_series()[0]
    latest_df = df.filter(pl.col("snapshot_date") == latest_date) if latest_date else df

    total_value = float(latest_df.select(pl.col("market_value").sum()).to_series()[0] or 0.0)
    account_count = int(latest_df.select(pl.col("account_id").n_unique()).to_series()[0])
    position_count = latest_df.height

    # Account breakdown
    accounts = (
        latest_df.group_by("account_id")
        .agg(
            pl.col("market_value").sum().alias("total_value"),
            pl.len().alias("positions"),
        )
        .sort("total_value", descending=True)
    )

    return {
        "has_data": True,
        "available_months": months,
        "latest_month": month_label,
        "snapshot_date": str(latest_date) if latest_date else None,
        "total_value": total_value,
        "account_count": account_count,
        "position_count": position_count,
        "accounts": accounts.to_dicts(),
    }


def _render_status(result: dict[str, Any]) -> None:
    """Render asset status as Rich output."""
    if not result.get("has_data"):
        info("자산 스냅샷 없음. finjuice import로 자산 시트를 먼저 수집하세요.")
        return

    section("Asset Portfolio Status")

    table_summary(
        "Portfolio Overview",
        [
            ("Snapshot Date", result["snapshot_date"] or "-"),
            ("Total Value", _format_krw(result["total_value"])),
            ("Accounts", str(result["account_count"])),
            ("Positions", str(result["position_count"])),
            ("Available Months", ", ".join(result["available_months"])),
        ],
    )

    # Account breakdown
    if result["accounts"]:
        acct_table = Table(title="Account Breakdown")
        acct_table.add_column("Account", style="cyan")
        acct_table.add_column("Value", justify="right", style="green")
        acct_table.add_column("Positions", justify="right")

        for acct in result["accounts"]:
            acct_table.add_row(
                str(acct["account_id"]),
                _format_krw(acct["total_value"]),
                str(acct["positions"]),
            )
        console.print(acct_table)

    success(f"Latest snapshot: {result['snapshot_date']}")


def _build_show_result(
    snapshots_dir: Path,
    month: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Build detailed holdings data."""
    if month:
        df = load_snapshot_partition(snapshots_dir, month)
        if df is None:
            return {"has_data": False, "error": f"No snapshot for {month}"}
        month_label = month
    else:
        loaded_df, loaded_label = load_latest_snapshot_partition(snapshots_dir)
        if loaded_df is None:
            return {"has_data": False, "error": "No snapshot data found"}
        df = loaded_df
        month_label = loaded_label or ""

    if df.is_empty():
        return {"has_data": False, "error": "Snapshot partition is empty"}

    # Use latest date within partition
    latest_date = df.select(pl.col("snapshot_date").max()).to_series()[0]
    df = df.filter(pl.col("snapshot_date") == latest_date) if latest_date else df

    if account:
        df = df.filter(pl.col("account_id").str.contains(account))

    df = df.sort("market_value", descending=True).head(limit)

    return {
        "has_data": True,
        "month": month_label,
        "snapshot_date": str(latest_date) if latest_date else None,
        "total_count": df.height,
        "holdings": [
            {
                "account_id": row["account_id"],
                "instrument_id": row["instrument_id"],
                "quantity": row["quantity"],
                "market_value": row["market_value"],
                "currency": row["currency"],
            }
            for row in df.to_dicts()
        ],
    }


def _render_show(result: dict[str, Any]) -> None:
    """Render detailed holdings table."""
    if not result.get("has_data"):
        info(result.get("error", "No data available"))
        return

    table = Table(
        title=f"Holdings — {result.get('snapshot_date', result.get('month', 'latest'))}",
    )
    table.add_column("Account", style="cyan")
    table.add_column("Instrument", style="yellow")
    table.add_column("Quantity", justify="right")
    table.add_column("Market Value", justify="right", style="green")
    table.add_column("Currency")

    for h in result["holdings"]:
        table.add_row(
            str(h["account_id"]),
            str(h["instrument_id"]),
            f"{h['quantity']:,.2f}",
            _format_krw(h["market_value"]),
            str(h["currency"]),
        )

    console.print(table)
    typer.echo(f"\n📊 {result['total_count']} positions")


@assets_app.command()
def status(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show asset portfolio overview."""
    config = get_config(ctx)
    snapshots_dir = config.data_dir / "assets" / "snapshots"

    try:
        result = _build_status_result(snapshots_dir)
        emit(result, json_output, _render_status, command="assets status")
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error(f"Failed to load asset status: {exc}", exc_info=True)
        emit_error(
            f"Failed to load asset status: {exc}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="assets status",
        )


@assets_app.command()
def show(
    ctx: typer.Context,
    month: Optional[str] = typer.Option(None, "--month", help="Snapshot month (YYYY-MM)"),
    account: Optional[str] = typer.Option(None, "--account", help="Filter by account ID"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max positions to show"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show detailed holdings."""
    config = get_config(ctx)
    snapshots_dir = config.data_dir / "assets" / "snapshots"

    try:
        result = _build_show_result(snapshots_dir, month=month, account=account, limit=limit)

        if not result.get("has_data"):
            emit_error(
                result.get("error", "No data"),
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=json_output,
                command="assets show",
            )

        emit(result, json_output, _render_show, command="assets show")
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error(f"Failed to load holdings: {exc}", exc_info=True)
        emit_error(
            f"Failed to load holdings: {exc}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="assets show",
        )
