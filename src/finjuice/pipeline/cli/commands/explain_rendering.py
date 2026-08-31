"""Human-readable Rich rendering for ``finjuice explain``.

Owns the transaction-details, classification, and rule-trace table. Search,
selection, explanation compute, and the Typer command stay in
:mod:`finjuice.pipeline.cli.commands.explain`, which re-exports the names
used by existing callers.
"""

from __future__ import annotations

from typing import Any, cast

from rich.table import Table

from finjuice.pipeline.cli.output import console, error, success


def render_explain(result: dict[str, Any]) -> None:
    """Render explain result as Rich output."""
    target_row = result["transaction"]
    classification = result["classification"]
    rule_trace = result["rule_trace"]

    console.print("\n[bold]🔍 Transaction Details:[/bold]")
    console.print(f"Date: {target_row['date']}")
    console.print(f"Merchant: {target_row['merchant_raw']}")
    console.print(f"Amount: {target_row['amount']}")
    console.print(f"Memo: {target_row['memo_raw']}")
    console.print("-" * 40)

    console.print("[bold]🏷️  Classification Result:[/bold]")

    if classification["matched_rules"]:
        success(f"Matched Rules: {', '.join(classification['matched_rules'])}")
        console.print(f"📋 Applied Tags: {', '.join(classification['tags'])}")
        if classification["category_rule"]:
            console.print(f"📂 Category: {classification['category_rule']}")
        else:
            console.print("📂 Category: (No category set by rules, using raw category)")

        # Detail breakdown
        console.print("\n[bold]Rule Trace:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Priority")
        table.add_column("Rule Name")
        table.add_column("Matched Field")
        table.add_column("Tags Added")
        table.add_column("Category Set")

        for trace in rule_trace:
            table.add_row(
                str(trace["priority"]),
                str(trace["rule_name"]),
                str(trace["matched_field"]),
                ", ".join(cast(list[str], trace["tags_added"])),
                str(trace["category_set"] or "-"),
            )
        console.print(table)
    else:
        error("No rules matched this transaction.")
        console.print("It will be classified as 'Unclassified' or use its raw category.")
