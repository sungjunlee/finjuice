"""Human-readable Rich rendering for ``finjuice review``.

Owns KRW formatting, confidence formatting, and the review table. Filter
predicates live in :mod:`finjuice.pipeline.cli.commands.review_filters`.
Data loading, JSON row projection, and the Typer command stay in
:mod:`finjuice.pipeline.cli.commands.review`, which re-exports the names
used by existing callers.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from finjuice.pipeline.cli import output as cli_output
from finjuice.pipeline.cli.output import console


def _format_amount(amount: Any) -> str:
    """Format a transaction amount as Korean won."""
    if amount is None:
        return "-"

    amount_value = float(amount)
    formatted = f"₩{abs(amount_value):,.0f}"
    return f"-{formatted}" if amount_value < 0 else formatted


def _format_confidence(confidence: Any) -> str:
    """Format a confidence score for table output."""
    if confidence is None:
        return "-"
    return f"{float(confidence):.2f}"


def _render_review(result: dict[str, Any]) -> None:
    """Render review results as a Rich table."""
    transactions = result["transactions"]
    filters = result.get("filters") or {}
    month_label = "all history" if filters.get("all_history") else result.get("month") or "latest"

    if not transactions:
        typer.echo("📝 No transactions match the review filters.")
        return

    table = Table(title=f"Transactions Requiring Review ({month_label})")
    table.add_column("Date", style="cyan")
    table.add_column("Merchant", style="yellow")
    table.add_column("Amount", justify="right", style="green")
    table.add_column("Category", style="magenta")
    table.add_column("Tags", style="blue")
    table.add_column("Confidence", justify="right", style="white")

    for row in transactions:
        merchant = row.get("merchant_raw") or "N/A"
        if len(merchant) > 30:
            merchant = merchant[:27] + "..."

        tags = row.get("tags_final") or []
        tags_display = ", ".join(tags) if tags else "-"

        table.add_row(
            str(row.get("date") or "-"),
            merchant,
            _format_amount(row.get("amount")),
            str(row.get("category_final") or "미분류"),
            tags_display,
            _format_confidence(row.get("confidence")),
        )

    console.print(table)
    typer.echo(f"\n📊 Showing {result['total_count']} transactions")
    pagination_dict = result.get("pagination")
    if isinstance(pagination_dict, dict):
        pagination = cli_output.Pagination(
            limit=int(pagination_dict.get("limit", 0)),
            cursor=str(pagination_dict.get("cursor", "0")),
            next_cursor=pagination_dict.get("next_cursor"),
            has_more=bool(pagination_dict.get("has_more", False)),
            total_estimate=pagination_dict.get("total_estimate"),
            truncated_by_bytes=bool(pagination_dict.get("truncated_by_bytes", False)),
        )
        cli_output.render_pagination_footer(len(transactions), pagination)
