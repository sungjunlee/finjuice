"""Human-readable Rich rendering for ``finjuice audit``.

Owns audit log/stats/clear tables, event detail formatting, and
template-run metric sections. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.audit`. JSONL I/O lives in
:mod:`finjuice.pipeline.cli.commands.audit_io`.
"""

from __future__ import annotations

from typing import Any, cast

from rich.table import Table

from finjuice.pipeline.cli.commands.audit_template_metrics import (
    TemplateMetrics,
    TemplateRunSummary,
    _parse_duration,
)
from finjuice.pipeline.cli.output import console, success


def _render_top_template_section(title: str, usage_counts: dict[str, int]) -> None:
    """Render a top-template usage section with a fixed top-5 limit."""
    console.print(f"\n[bold]{title}[/bold]")
    top_templates = sorted(usage_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_templates:
        for template_name, count in top_templates:
            console.print(f"  {count:3d}× {template_name}")
    else:
        console.print("  (none)")


def _new_metrics_table() -> Table:
    """Create a Rich table for template metrics output."""
    template_table = Table(show_header=False, box=None, padding=(0, 2))
    template_table.add_column("Metric", style="bold")
    template_table.add_column("Value")
    return template_table


def _add_overall_metric_rows(table: Table, metrics: TemplateMetrics) -> None:
    """Add overall template metric rows."""
    table.add_row("Template runs", str(metrics.total))
    table.add_row("  ├─ Successful", f"[green]{metrics.success}[/green]")
    table.add_row("  └─ Failed", f"[red]{metrics.failed}[/red]")
    table.add_row("Success rate", f"{metrics.success_rate:.1f}%")
    table.add_row("Avg duration", f"{metrics.avg_duration:.2f}s")
    table.add_row("Retry attempts", str(metrics.retry_attempts))
    table.add_row("Retry recovery", f"{metrics.retry_recovery:.1f}%")
    table.add_row("", "")


def _add_domain_metric_rows(table: Table, label: str, metrics: TemplateMetrics) -> None:
    """Add per-domain template metric rows."""
    table.add_row(f"{label} runs", str(metrics.total))
    table.add_row(f"  ├─ {label} successful", f"[green]{metrics.success}[/green]")
    table.add_row(f"  └─ {label} failed", f"[red]{metrics.failed}[/red]")
    table.add_row(f"{label} success rate", f"{metrics.success_rate:.1f}%")
    table.add_row(f"{label} retry attempts", str(metrics.retry_attempts))
    table.add_row(f"{label} retry recovery", f"{metrics.retry_recovery:.1f}%")
    table.add_row("", "")


def _build_template_metrics_table(summary: TemplateRunSummary) -> Table:
    """Build a rendered table for template metrics."""
    table = _new_metrics_table()
    _add_overall_metric_rows(table, summary.overall)
    _add_domain_metric_rows(table, "Asset", summary.asset)
    _add_domain_metric_rows(table, "Transaction", summary.transaction)
    return table


def _render_template_run_metrics(summary: TemplateRunSummary) -> None:
    """Render template metrics table and top-usage sections."""
    console.print("\n[bold cyan]📈 Template Run Metrics[/bold cyan]\n")
    console.print(_build_template_metrics_table(summary))

    _render_top_template_section("Top Templates:", summary.usage_counts)
    _render_top_template_section("Top Asset Templates:", summary.domain_usage_counts["asset"])
    _render_top_template_section(
        "Top Transaction Templates:",
        summary.domain_usage_counts["transaction"],
    )


def _build_audit_log_details(event: dict[str, Any]) -> str:
    """Build the details column text for a single audit event."""
    event_name = event.get("event", "unknown")

    if event_name == "command_suggested":
        confirmed = event.get("user_confirmed")
        if confirmed is True:
            return "[green]✓ Confirmed[/green]"
        if confirmed is False:
            return "[yellow]✗ Declined[/yellow]"
        return "[dim]Pending[/dim]"

    if event_name == "command_executed":
        success = event.get("success", False)
        duration = event.get("duration", 0)
        returncode = event.get("returncode", 0)

        if success:
            return f"[green]✓ Success ({duration:.1f}s)[/green]"
        return f"[red]✗ Failed (code: {returncode})[/red]"

    if event_name == "command_error":
        stage = event.get("stage", "unknown")
        error_message = event.get("error_message", "Unknown error")
        return f"[red]{stage}: {error_message[:40]}...[/red]"

    if event_name == "template_run":
        template_name = event.get("template_name", "unknown")
        success = event.get("success") is True
        duration = _parse_duration(event)
        if success:
            return f"[green]✓ {template_name} ({duration:.1f}s)[/green]"
        error_type = event.get("error_type", "Error")
        return f"[red]✗ {template_name} ({error_type})[/red]"

    return ""


def _render_audit_log(result: dict[str, Any]) -> None:
    """Render human-readable audit log output."""
    events = cast(list[dict[str, Any]], result["events"])
    count = int(result["count"])

    if not events:
        console.print("[dim]No events found matching filters.[/dim]")
        return

    console.print(f"\n[bold cyan]📋 Audit Log ({count} events)[/bold cyan]\n")

    table = Table(show_header=True)
    table.add_column("Timestamp", style="dim")
    table.add_column("Event", style="bold")
    table.add_column("Command", style="cyan")
    table.add_column("Details")

    for event in events:
        timestamp = str(event.get("timestamp", "N/A"))[:19]
        event_name = str(event.get("event", "unknown"))
        command = str(event.get("command", "N/A"))
        details = _build_audit_log_details(event)
        table.add_row(timestamp, event_name, command, details)

    console.print(table)
    console.print()


def _render_audit_stats(result: dict[str, Any]) -> None:
    """Render human-readable audit statistics output."""
    suggestions = cast(dict[str, int], result["suggestions"])
    executions = cast(dict[str, int], result["executions"])
    success_rate = cast(float | None, result["success_rate"])
    top_commands = cast(list[dict[str, Any]], result["top_commands"])

    console.print("\n[bold cyan]📊 Audit Log Statistics[/bold cyan]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Total suggestions", str(suggestions["total"]))
    table.add_row("  ├─ Confirmed", f"[green]{suggestions['confirmed']}[/green]")
    table.add_row("  └─ Declined", f"[yellow]{suggestions['declined']}[/yellow]")
    table.add_row("", "")
    table.add_row("Total executions", str(executions["total"]))
    table.add_row("  ├─ Successful", f"[green]{executions['successful']}[/green]")
    table.add_row("  └─ Failed", f"[red]{executions['failed']}[/red]")

    if success_rate is not None:
        table.add_row("Success rate", f"{success_rate:.1f}%")

    console.print(table)

    if top_commands:
        console.print("\n[bold]Top Commands:[/bold]")
        for top_command in top_commands:
            command = str(top_command["command"])
            count = int(top_command["count"])
            console.print(f"  {count:3d}× {command}")

    template_summary = cast(TemplateRunSummary | None, result.get("_template_summary"))
    if template_summary is not None:
        _render_template_run_metrics(template_summary)

    console.print()


def _render_audit_clear(result: dict[str, Any]) -> None:
    """Render human-readable audit clear output."""
    entries_kept = int(result["entries_kept"])
    success(f"Cleared audit log (kept last {entries_kept} entries)", prefix="✓")
