"""Next-step and footnote rendering for the ``finjuice status`` command."""

from __future__ import annotations

from finjuice.pipeline.cli.output import console

TAGGING_TERMINOLOGY_REFERENCE = "docs/reference/tagging-review-terminology.md"


def _render_status_footnotes(filters_applied: int) -> None:
    """Render filter and terminology notes under the main status table."""
    if filters_applied > 0:
        console.print(
            f"[dim]active filters: {filters_applied} "
            "(use --no-filter to compare full results)[/dim]"
        )
    console.print(
        "[dim]Terminology: untagged = tags_final empty; "
        "suggestable_untagged excludes confirmed transfers. "
        f"See {TAGGING_TERMINOLOGY_REFERENCE}[/dim]"
    )
    console.print()


def _render_next_steps(
    *,
    rules_exists: bool,
    suggestable_untagged_count: int,
    transfer_excluded_untagged_count: int,
    schema_migration: dict[str, str] | None,
) -> None:
    """Render human next-step recommendations."""
    next_steps: list[tuple[str, str]] = []

    if schema_migration:
        next_steps.append((schema_migration["command"], schema_migration["message"]))

    if not rules_exists:
        next_steps.append(("finjuice init", "Set up rules.yaml template"))
    elif suggestable_untagged_count > 0:
        desc = f"Get suggestions for {suggestable_untagged_count} suggestable untagged"
        if transfer_excluded_untagged_count > 0:
            desc += f" ({transfer_excluded_untagged_count} transfer-excluded)"
        next_steps.append(("finjuice rules suggest", desc))
        next_steps.append(("finjuice tag", "Apply existing rules to transactions"))
    elif transfer_excluded_untagged_count > 0:
        next_steps.append(
            (
                "finjuice review --untagged",
                f"Review {transfer_excluded_untagged_count} transfer-excluded untagged",
            )
        )
    else:
        next_steps.append(("finjuice template list", "Browse curated SQL analyses"))
        next_steps.append(("finjuice query --help", "Run custom SQL analysis"))
        next_steps.append(("finjuice export", "Generate reports and master.xlsx"))

    if next_steps:
        console.print("[bold cyan]💡 Next Steps[/bold cyan]")
        for cmd, desc in next_steps:
            console.print(f"  [green]{cmd}[/green]  →  {desc}")
        console.print()
