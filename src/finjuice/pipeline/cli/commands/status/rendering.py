"""Payload assembly and Rich rendering for the ``finjuice status`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.table import Table

from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.storage.schema_registry import (
    SchemaCompatibilityState,
    get_schema_migration_guidance,
)

from .compute import StatusFacts
from .detector import StatusDiagnoses

TRANSFER_EXCLUSION_DESCRIPTION = (
    "Only rows where is_transfer == 1 and transfer_group_id is present are excluded; "
    "unconfirmed transfer candidates remain reportable."
)
TAGGING_TERMINOLOGY_REFERENCE = "docs/reference/tagging-review-terminology.md"
STATUS_SCHEMA_REFERENCE = "schemas/status.schema.json"
TAGGING_TERMINOLOGY_DEFINITIONS = {
    "untagged": "tags_final is null or an empty tag array; transfer rows are included.",
    "suggestable_untagged": (
        "untagged rows eligible for rules suggest after excluding confirmed transfers."
    ),
    "uncategorized": "category_final is the fallback category 미분류.",
    "rule_matched": "tags_rule or category_rule contains rule-derived output.",
    "needs_review": "the explicit row flag needs_review == 1.",
}


@dataclass(frozen=True)
class StatusRenderContext:
    """Render-only context that should not be serialized in status JSON."""

    top_n: int
    filters_applied: int


@dataclass(frozen=True)
class StatusResult:
    """Computed status payload plus rendering metadata."""

    payload: dict[str, Any]
    render_context: StatusRenderContext


def build_status_result(facts: StatusFacts, diagnoses: StatusDiagnoses) -> StatusResult:
    """Assemble the public status payload from facts and diagnoses."""
    schema_payload = facts.schema_summary.to_dict()
    if facts.schema_summary.state is not SchemaCompatibilityState.ACTIVE:
        schema_payload["migration"] = get_schema_migration_guidance(
            facts.schema_summary,
            metadata_dir=facts.data_dir / "metadata",
        )

    payload: dict[str, Any] = {
        "data_directory": {
            "path": facts.data_dir_resolved,
            "source": facts.data_dir_source,
        },
        "transactions": {
            "count": facts.total_rows,
            "date_range": {
                "start": facts.min_date,
                "end": facts.max_date,
            },
            "partition_count": facts.partition_count,
        },
        "schema": schema_payload,
        "last_import": {
            "imported_at": facts.last_import_date,
            "file_id": facts.last_import_file,
        },
        "terminology": {
            "reference": TAGGING_TERMINOLOGY_REFERENCE,
            "schema": STATUS_SCHEMA_REFERENCE,
            "definitions": dict(TAGGING_TERMINOLOGY_DEFINITIONS),
        },
        "tagging": {
            "tagged_count": facts.tagged_count,
            "untagged_count": facts.untagged_count,
            "tagging_rate": facts.tagging_rate,
            "suggestable_transaction_count": facts.suggestable_transaction_count,
            "suggestable_tagged_count": facts.suggestable_tagged_count,
            "suggestable_untagged_count": facts.suggestable_untagged_count,
            "suggestable_tagging_rate": facts.suggestable_tagging_rate,
            "transfer_candidate_count": facts.transfer_candidate_count,
            "transfer_excluded_count": facts.transfer_excluded_count,
            "transfer_excluded_untagged_count": facts.transfer_excluded_untagged_count,
            "unconfirmed_transfer_candidate_count": (facts.unconfirmed_transfer_candidate_count),
            "transfer_exclusions": {
                "excluded_count": facts.transfer_excluded_count,
                "confirmed_count": facts.transfer_excluded_count,
                "candidate_count": facts.transfer_candidate_count,
                "unconfirmed_candidate_count": facts.unconfirmed_transfer_candidate_count,
                "excluded_untagged_count": facts.transfer_excluded_untagged_count,
                "definition": TRANSFER_EXCLUSION_DESCRIPTION,
            },
            "untagged_merchants": facts.untagged_merchants,
            "untagged_merchants_total": facts.untagged_merchants_total,
        },
        "rules_file": {
            "path": str(facts.rules_path),
            "exists": facts.rules_exists,
            "modified_at": facts.rules_modified,
        },
    }
    payload["health"] = diagnoses.health
    payload["actionable"] = diagnoses.actionable
    payload["signals"] = diagnoses.signals
    payload["next_steps"] = diagnoses.next_steps
    if facts.detailed_stats is not None:
        payload["detailed_stats"] = facts.detailed_stats
        payload["detailed_stats_warning"] = facts.detailed_stats_warning

    return StatusResult(
        payload=payload,
        render_context=StatusRenderContext(
            top_n=facts.top_n,
            filters_applied=facts.filters_applied,
        ),
    )


def emit_status_result(result: StatusResult, *, json_output: bool) -> None:
    """Emit a computed status result in JSON or human-readable form."""
    if json_output:
        emit(
            result.payload,
            json_output=True,
            render_fn=lambda _: None,
            command="status",
            meta_extras={"filters_applied": result.render_context.filters_applied},
        )
        return

    render_status(result)


def render_status(status_result: StatusResult) -> None:
    """Render status data as Rich console output."""
    result = status_result.payload
    console.print("\n[bold cyan]📊 Finance Data Status[/bold cyan]\n")
    console.print(_build_status_table(result))
    _render_status_footnotes(status_result.render_context.filters_applied)

    detailed_stats = result.get("detailed_stats")
    if detailed_stats:
        _render_detailed_stats(
            detailed_stats,
            result.get("detailed_stats_warning"),
            status_result.render_context.top_n,
        )

    _render_next_steps(
        rules_exists=result["rules_file"]["exists"],
        suggestable_untagged_count=result["tagging"]["suggestable_untagged_count"],
        transfer_excluded_untagged_count=result["tagging"]["transfer_excluded_untagged_count"],
        schema_migration=result["schema"].get("migration"),
    )


def _build_status_table(result: dict[str, Any]) -> Table:
    """Build the main status table."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    _add_data_rows(table, result)
    _add_schema_row(table, result)
    _add_import_row(table, result)
    _add_tagging_rate_row(table, result)
    _add_transfer_rows(table, result)
    _add_untagged_rows(table, result)
    _add_rules_row(table, result)
    return table


def _add_data_rows(table: Table, result: dict[str, Any]) -> None:
    """Add directory, range, and partition rows."""
    data_dir_resolved = result["data_directory"]["path"]
    data_dir_source = result["data_directory"]["source"]
    min_date = result["transactions"]["date_range"]["start"]
    max_date = result["transactions"]["date_range"]["end"]
    date_range = f"{min_date} to {max_date}" if min_date and max_date else "N/A"

    table.add_row("Data directory", f"{data_dir_resolved} [dim]({data_dir_source})[/dim]")
    table.add_row("Transactions", f"{result['transactions']['count']:,} rows")
    table.add_row("Date range", date_range)
    table.add_row("Partitions", f"{result['transactions']['partition_count']} months")


def _add_schema_row(table: Table, result: dict[str, Any]) -> None:
    """Add schema compatibility state and migration hint."""
    schema = result["schema"]
    state = schema["state"]
    if state == SchemaCompatibilityState.ACTIVE.value:
        versions = schema.get("active_versions") or [schema["current_version"]]
        table.add_row("Schema", f"active v{versions[-1]}")
        return

    migration = schema.get("migration") or {}
    if state == SchemaCompatibilityState.COMPATIBLE_LEGACY.value:
        versions = ", ".join(f"v{version}" for version in schema["compatible_legacy_versions"])
        table.add_row(
            "Schema",
            f"[yellow]compatible legacy schema {versions}[/yellow] - run {migration['command']}",
        )
        return

    table.add_row(
        "Schema",
        f"[red]unsupported schema[/red] - run {migration.get('command', 'finjuice doctor')}",
    )


def _add_import_row(table: Table, result: dict[str, Any]) -> None:
    """Add the latest import row."""
    last_import_date = result["last_import"]["imported_at"]
    last_import_file = result["last_import"]["file_id"]
    if last_import_date and last_import_file:
        table.add_row("Last import", f"{last_import_date} (file_id: {last_import_file})")
    else:
        table.add_row("Last import", "[dim]No imports yet[/dim]")


def _add_tagging_rate_row(table: Table, result: dict[str, Any]) -> None:
    """Add the tagging-rate row when transaction data exists."""
    total_rows = result["transactions"]["count"]
    if total_rows <= 0:
        return

    tagged_count = result["tagging"]["tagged_count"]
    tagging_rate = result["tagging"]["tagging_rate"]
    rate_style = _tagging_rate_style(tagging_rate)
    table.add_row(
        "Tagging rate",
        f"[{rate_style}]{tagging_rate:.1f}%[/{rate_style}] ({tagged_count:,} / {total_rows:,})",
    )


def _tagging_rate_style(tagging_rate: float) -> str:
    """Return the Rich style for a tagging rate."""
    if tagging_rate >= 95:
        return "green"
    if tagging_rate >= 80:
        return "yellow"
    return "red"


def _add_transfer_rows(table: Table, result: dict[str, Any]) -> None:
    """Add transfer candidate/confirmed counts."""
    candidate_count = result["tagging"]["transfer_candidate_count"]
    confirmed_count = result["tagging"]["transfer_excluded_count"]
    unconfirmed_count = result["tagging"]["unconfirmed_transfer_candidate_count"]
    if candidate_count == 0:
        return

    table.add_row(
        "Transfers",
        (
            f"{confirmed_count:,} confirmed excluded; "
            f"{unconfirmed_count:,} unconfirmed candidates kept"
        ),
    )


def _add_untagged_rows(table: Table, result: dict[str, Any]) -> None:
    """Add untagged count and top merchant rows."""
    untagged_count = result["tagging"]["untagged_count"]
    suggestable_untagged_count = result["tagging"]["suggestable_untagged_count"]
    transfer_excluded_untagged_count = result["tagging"]["transfer_excluded_untagged_count"]
    untagged_merchant_list = result["tagging"]["untagged_merchants"]

    if untagged_count == 0:
        table.add_row("Untagged", "[green]All transactions tagged ✓[/green]")
    elif transfer_excluded_untagged_count > 0:
        table.add_row(
            "Untagged",
            (
                f"[yellow]{untagged_count:,} total[/yellow]; "
                f"{suggestable_untagged_count:,} rule-suggestable "
                f"({transfer_excluded_untagged_count:,} transfer-excluded)"
            ),
        )
    else:
        table.add_row(
            "Untagged",
            f"[yellow]{untagged_count:,} transactions need review[/yellow]",
        )

    if untagged_merchant_list:
        merchant_list = ", ".join(
            f"{merchant['merchant']}({merchant['count']})"
            for merchant in untagged_merchant_list[:5]
        )
        table.add_row("Top untagged", f"[dim]{merchant_list}[/dim]")


def _add_rules_row(table: Table, result: dict[str, Any]) -> None:
    """Add the rules file status row."""
    rules_path_str = result["rules_file"]["path"]
    rules_exists = result["rules_file"]["exists"]
    rules_modified = result["rules_file"]["modified_at"]
    if rules_exists:
        table.add_row("Rules file", f"{Path(rules_path_str).name} (modified: {rules_modified})")
    else:
        table.add_row("Rules file", "[yellow]Not found - run 'finjuice init'[/yellow]")


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


def _render_detailed_stats(
    detailed_stats: dict[str, Any],
    detailed_warning: Any,
    top_n: int,
) -> None:
    """Render the optional detailed status snapshot."""
    console.print("[bold cyan]📈 Detailed Snapshot[/bold cyan]")
    if detailed_stats.get("data_range"):
        console.print(f"  Data range: {detailed_stats['data_range']}")
    console.print(f"  Active filters: {detailed_stats.get('active_filters', 0)}")
    console.print(f"  Active goals: {len(detailed_stats.get('active_goals', []))}")

    if detailed_warning:
        console.print(f"  [yellow]{detailed_warning}[/yellow]")
        return

    _render_detailed_amounts(detailed_stats)
    _render_structural_sources(detailed_stats, top_n)
    _render_top_categories(detailed_stats, top_n)


def _render_detailed_amounts(detailed_stats: dict[str, Any]) -> None:
    """Render detailed averages, rates, and structural total."""
    if detailed_stats.get("monthly_avg_income") is not None:
        console.print(f"  월평균 수입: {_format_currency(detailed_stats['monthly_avg_income'])}")
    if detailed_stats.get("monthly_avg_expense") is not None:
        console.print(f"  월평균 지출: {_format_currency(detailed_stats['monthly_avg_expense'])}")
    if detailed_stats.get("monthly_avg_consumption_expense") is not None:
        console.print(
            "  월평균 소비성 지출: "
            f"{_format_currency(detailed_stats['monthly_avg_consumption_expense'])}"
        )
    if detailed_stats.get("residual_savings_rate_3mo") is not None:
        console.print(
            f"  최근 3개월 잔여 현금흐름 저축률: {detailed_stats['residual_savings_rate_3mo']:.0%}"
        )
    if detailed_stats.get("consumption_savings_rate_3mo") is not None:
        console.print(
            f"  최근 3개월 소비 기준 저축률: {detailed_stats['consumption_savings_rate_3mo']:.0%}"
        )
    structural_avg = int(detailed_stats.get("structural_savings_monthly_avg") or 0)
    if structural_avg > 0:
        console.print(f"  월평균 구조적 저축: {_format_currency(structural_avg)}")
    console.print()


def _render_structural_sources(detailed_stats: dict[str, Any], top_n: int) -> None:
    """Render detailed structural savings sources."""
    structural_sources = detailed_stats.get("structural_savings_sources") or []
    if not structural_sources:
        return

    console.print("[bold cyan]💾 구조적 저축[/bold cyan]")
    for source in structural_sources[:top_n]:
        label = str(source.get("label") or source.get("source") or "-")
        monthly_amount = _format_currency(float(source.get("monthly_amount") or 0))
        provenance = str(source.get("source") or "-")
        tags = ", ".join(source.get("tags") or [])
        suffix = f" [{tags}]" if tags else ""
        console.print(f"  - {label}: {monthly_amount}/월 ({provenance}){suffix}")
    console.print()


def _render_top_categories(detailed_stats: dict[str, Any], top_n: int) -> None:
    """Render detailed top categories."""
    top_categories = detailed_stats.get("top_categories") or []
    if not top_categories:
        return

    console.print(f"[bold cyan]📂 Top {top_n} 카테고리[/bold cyan]")
    for index, category in enumerate(top_categories, 1):
        console.print(
            f"  {index}. {category['name']:16} {_format_currency(float(category['amount'])):>12}"
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


def _format_currency(amount: float) -> str:
    """Format amount as Korean won."""
    if amount >= 100_000_000:
        return f"₩{amount / 100_000_000:.1f}억"
    if amount >= 10_000_000:
        return f"₩{amount / 10_000:.0f}만"
    if amount >= 1_000_000:
        return f"₩{amount / 10_000:.1f}만"
    return f"₩{amount:,.0f}"
