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

from finjuice.pipeline.cli.commands.assets_reads import (
    latest_portfolio_partition,
    load_portfolio_display,
    portfolio_holding_evidence,
    portfolio_meta,
    render_portfolio_identity,
    safe_portfolio_error,
)
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
from finjuice.pipeline.portfolio_display import PortfolioDisplay

logger = logging.getLogger(__name__)

assets_app = typer.Typer(
    name="assets",
    help="View raw asset snapshot rows and per-position holdings",
)


def _build_status_result(
    snapshots_dir: Path,
    *,
    display: PortfolioDisplay | None = None,
) -> dict[str, Any]:
    """Build asset status data."""
    months = (
        list(display.snapshot_months)
        if display is not None
        else discover_snapshot_months(snapshots_dir)
    )
    if not months:
        return {"has_data": False}

    df, month_label = (
        (display.snapshot_partition(months[-1]), months[-1])
        if display is not None
        else load_latest_snapshot_partition(snapshots_dir)
    )
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
    *,
    display: PortfolioDisplay | None = None,
) -> dict[str, Any]:
    """Build detailed holdings data."""
    if month:
        df = (
            display.snapshot_partition(month)
            if display is not None
            else load_snapshot_partition(snapshots_dir, month)
        )
        if df is None:
            return {"has_data": False, "error": f"No snapshot for {month}"}
        month_label = month
    else:
        if display is None:
            loaded_df, loaded_label = load_latest_snapshot_partition(snapshots_dir)
        else:
            loaded_df, loaded_label = latest_portfolio_partition(display, "snapshot")
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
                **(portfolio_holding_evidence(row) if display is not None else {}),
            }
            for row in df.to_dicts()
        ],
    }


def _build_balance_result(
    balance_dir: Path, *, display: PortfolioDisplay | None = None
) -> dict[str, Any]:
    """Build latest Banksalad overview balance data."""
    if display is None:
        df, month_label = load_latest_balance_partition(balance_dir)
    else:
        df, month_label = latest_portfolio_partition(display, "balance")
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

    display = None
    try:
        display = load_portfolio_display(ctx, config.data_dir)
        result = _build_status_result(snapshots_dir, display=display)
        emit(
            result,
            json_output,
            _render_status,
            command="assets status",
            meta_extras=portfolio_meta(display),
        )
        render_portfolio_identity(display, json_output=json_output)
    except Exception as exc:  # intended catch-all for CLI robustness
        message = safe_portfolio_error(exc, display)
        logger.error("Failed to load asset status: %s", message)
        emit_error(
            f"Failed to load asset status: {message}",
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

    display = None
    try:
        display = load_portfolio_display(ctx, config.data_dir)
        result = _build_balance_result(balance_dir, display=display)
        emit(
            result,
            json_output,
            _render_balance,
            command="assets balance",
            meta_extras=portfolio_meta(display),
        )
        render_portfolio_identity(display, json_output=json_output)
    except Exception as exc:  # intended catch-all for CLI robustness
        message = safe_portfolio_error(exc, display)
        logger.error("Failed to load Banksalad overview balance: %s", message)
        emit_error(
            f"Failed to load Banksalad overview balance: {message}",
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

    display = None
    try:
        display = load_portfolio_display(ctx, config.data_dir)
        result = _build_show_result(
            snapshots_dir, month=month, account=account, limit=limit, display=display
        )

        if not result.get("has_data"):
            emit_error(
                result.get("error", "No data"),
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=json_output,
                command="assets show",
                meta_extras=portfolio_meta(display),
            )

        emit(
            result,
            json_output,
            _render_show,
            command="assets show",
            meta_extras=portfolio_meta(display),
        )
        render_portfolio_identity(display, json_output=json_output)
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        message = safe_portfolio_error(exc, display)
        logger.error("Failed to load holdings: %s", message)
        emit_error(
            f"Failed to load holdings: {message}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="assets show",
        )
