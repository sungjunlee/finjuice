"""Human-readable Rich rendering for ``finjuice show``.

Owns KRW formatting, cell truncation, the transactions table, and the
summary footer. Partition loading, filters, and JSON payloads stay in
:mod:`finjuice.pipeline.cli.commands.show_cmd`.
"""

from __future__ import annotations

from typing import Any

import polars as pl
import typer
from rich.table import Table

from finjuice.pipeline.cli.output import Pagination, console, render_pagination_footer


def _format_amount(amount: float) -> str:
    """Format a transaction amount as signed KRW."""
    amount_str = f"₩{abs(amount):,.0f}"
    if amount < 0:
        return f"-{amount_str}"
    return amount_str


def _truncate_display(value: Any, max_len: int) -> Any:
    """Truncate a display string with an ellipsis when it exceeds *max_len*."""
    if len(value) > max_len:
        return value[: max_len - 3] + "..."
    return value


def _format_tags(tags: Any) -> str:
    """Format ``tags_final`` for the human table."""
    if tags and isinstance(tags, list) and len(tags) > 0:
        return ", ".join(str(t) for t in tags)
    return "-"


def _render_show_table(
    df: pl.DataFrame,
    *,
    table_title: str,
    scope_hint: str,
    pagination: Pagination,
) -> None:
    """Render the human-readable show table, summary, and pagination footer."""
    if len(df) == 0:
        typer.echo("📝 No transactions match the filters.")
        return

    table = Table(title=table_title)
    table.add_column("Date", style="cyan")
    table.add_column("Merchant", style="yellow")
    table.add_column("Amount", justify="right", style="green")
    table.add_column("Tags", style="blue")
    table.add_column("Account", style="magenta")

    for row in df.iter_rows(named=True):
        merchant_display = _truncate_display(row.get("merchant_raw") or "N/A", 30)
        account = _truncate_display(row.get("account") or "N/A", 15)
        table.add_row(
            row["date"],
            merchant_display,
            _format_amount(row["amount"]),
            _format_tags(row.get("tags_final")),
            account,
        )

    console.print(table)

    total = len(df)
    total_amount = df["amount"].sum()
    typer.echo(f"\n📊 Showing {total} transactions{scope_hint}")
    typer.echo(f"💰 Total: ₩{abs(total_amount):,.0f}")
    render_pagination_footer(total, pagination)
