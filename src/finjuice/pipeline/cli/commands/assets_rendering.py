"""Human-readable Rich rendering for ``finjuice assets``.

Owns KRW formatting and the status/show/balance tables. The Typer commands
and JSON payloads stay in :mod:`finjuice.pipeline.cli.commands.assets`.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import console, info, section, success, table_summary


def _format_krw(amount: float) -> str:
    """Format amount as KRW."""
    return f"₩{abs(amount):,.0f}"


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


def _render_balance(result: dict[str, Any]) -> None:
    """Render Banksalad overview balance rows."""
    if not result.get("has_data"):
        info("뱅샐현황 balance 데이터가 없습니다. Banksalad XLSX를 import 하세요.")
        return

    section("Banksalad Overview Balance")
    table_summary(
        "Latest Balance",
        [
            ("Snapshot Date", result["snapshot_date"] or "-"),
            ("Total Assets", _format_krw(float(result["total_assets"]))),
            ("Total Liabilities", _format_krw(float(result["total_liabilities"]))),
        ],
    )

    for title, rows in (("Assets", result["assets"]), ("Liabilities", result["liabilities"])):
        if not rows:
            continue
        table = Table(title=title)
        table.add_column("Category", style="cyan")
        table.add_column("Item", style="yellow")
        table.add_column("Amount", justify="right", style="green")
        table.add_column("Currency")
        for row in rows:
            table.add_row(
                str(row["category"]),
                str(row["item_name"]),
                _format_krw(float(row["amount"])),
                str(row["currency"]),
            )
        console.print(table)
