"""Raw asset snapshot CLI commands.

Provides commands for viewing imported snapshot rows directly:
- status: Quick overview (total value, accounts, positions)
- show: Detailed holdings table

Human rendering lives in :mod:`finjuice.pipeline.cli.commands.assets_rendering`.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import polars as pl
import typer

from finjuice.pipeline.cli.commands.assets_rendering import (
    _render_balance,
    _render_show,
    _render_status,
)
from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    emit,
    emit_error,
)
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.networth import (
    discover_snapshot_months,
    load_latest_balance_partition,
    load_latest_snapshot_partition,
    load_snapshot_partition,
)

logger = logging.getLogger(__name__)

assets_app = typer.Typer(
    name="assets",
    help="View raw asset snapshot rows and per-position holdings",
)


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


def _build_balance_result(balance_dir: Path) -> dict[str, Any]:
    """Build latest Banksalad overview balance data."""
    df, month_label = load_latest_balance_partition(balance_dir)
    if df is None or df.is_empty():
        return {
            "has_data": False,
            "latest_month": None,
            "snapshot_date": None,
            "total_assets": 0.0,
            "total_liabilities": 0.0,
            "assets": [],
            "liabilities": [],
        }

    latest_date = df.select(pl.col("snapshot_date").max()).to_series()[0]
    latest_df = df.filter(pl.col("snapshot_date") == latest_date) if latest_date else df

    assets = _balance_side_rows(latest_df, "asset")
    liabilities = _balance_side_rows(latest_df, "liability")

    return {
        "has_data": True,
        "latest_month": month_label,
        "snapshot_date": str(latest_date) if latest_date else None,
        "total_assets": sum(float(row["amount"]) for row in assets),
        "total_liabilities": sum(float(row["amount"]) for row in liabilities),
        "assets": assets,
        "liabilities": liabilities,
    }


def _balance_side_rows(df: pl.DataFrame, side: str) -> list[dict[str, Any]]:
    rows = (
        df.filter(pl.col("side") == side)
        .group_by(["category", "item_name", "currency"])
        .agg(pl.col("amount").sum().alias("amount"))
        .sort("amount", descending=True)
        .to_dicts()
    )
    return [
        {
            "category": row["category"],
            "item_name": row["item_name"],
            "amount": float(row["amount"] or 0.0),
            "currency": row["currency"] or "KRW",
        }
        for row in rows
    ]


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
def balance(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show latest Banksalad overview balance rows."""
    config = get_config(ctx)
    balance_dir = config.data_dir / "banksalad" / "balance"

    try:
        result = _build_balance_result(balance_dir)
        emit(result, json_output, _render_balance, command="assets balance")
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to load Banksalad overview balance: %s", exc, exc_info=True)
        emit_error(
            f"Failed to load Banksalad overview balance: {exc}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="assets balance",
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
