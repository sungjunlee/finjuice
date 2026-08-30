"""Main status table row assembly for the ``finjuice status`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.table import Table

from finjuice.pipeline.storage.schema_registry import SchemaCompatibilityState


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
