"""Human-readable Rich rendering for ``finjuice rules test``.

Owns the summary header, the sample-rows table, and the month/cross-tag
counter tables. The Typer command, JSON payload, and data loading stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.testing`.
"""

from __future__ import annotations

from typing import Any

from rich.table import Table

from finjuice.pipeline.cli.output import console, warning


def _format_rules_test_amount(amount: Any) -> str:
    """Format sample amounts as signed integers with thousands separators."""
    if amount is None:
        return "-"
    try:
        return f"{int(float(amount)):,}"
    except (TypeError, ValueError):
        return str(amount)


def _format_rules_test_tags(tags: list[str]) -> str:
    """Render tags as a readable single line."""
    text = ", ".join(tags) if tags else "-"
    return text if len(text) <= 40 else text[:37] + "..."


def _render_rules_test_sample(rows: list[dict[str, Any]]) -> None:
    """Render the sample-rows table for `rules test`."""
    sample_table = Table(title="Sample Rows", show_header=True)
    sample_table.add_column("Date", style="cyan")
    sample_table.add_column("Merchant", style="yellow")
    sample_table.add_column("Amount", style="green", justify="right")
    sample_table.add_column("Account", style="white")
    sample_table.add_column("Category", style="magenta")
    sample_table.add_column("Tags", style="blue")
    for row in rows:
        sample_table.add_row(
            str(row.get("date") or "-"),
            str(row.get("merchant_raw") or "-"),
            _format_rules_test_amount(row.get("amount")),
            str(row.get("account") or "-"),
            str(row.get("category_final") or "-"),
            _format_rules_test_tags(row.get("tags_final") or []),
        )
    console.print(sample_table)


def _render_rules_test_counter_table(
    title: str, col_header: str, col_style: str, items: list[tuple[str, int]]
) -> None:
    """Render a small Rich table for month/cross-tag counts."""
    table = Table(title=title, show_header=True)
    table.add_column(col_header, style=col_style)
    table.add_column("Count", style="green", justify="right")
    for key, count in items:
        table.add_row(key, f"{count:,}")
    console.print(table)


def _format_rules_test_header(result: dict[str, Any]) -> str:
    """Build the bold summary header for `rules test` output."""
    scope = result["scope"]
    header = (
        f"Rule '{result['rule_name']}' — matched {result['match_count']} "
        f"of {scope['total_rows_scanned']} rows"
    )
    if scope.get("month"):
        header += f" (scope: {scope['month']})"
    return header


def _render_rules_test(result: dict[str, Any]) -> None:
    """Render `finjuice rules test` output with Rich tables."""
    console.print(f"[bold]{_format_rules_test_header(result)}[/bold]")
    if result["match_count"] == 0:
        warning("No rows matched. Run `finjuice rules validate` or edit the rule and retry.")
        return
    if result["sample"]:
        _render_rules_test_sample(result["sample"])
    if result["monthly_distribution"]:
        _render_rules_test_counter_table(
            "Monthly Distribution", "Month", "cyan", list(result["monthly_distribution"].items())
        )
    if result["cross_tags_top"]:
        cross_items = [(item["tag"], item["count"]) for item in result["cross_tags_top"]]
        _render_rules_test_counter_table("Top Cross Tags", "Tag", "blue", cross_items)
