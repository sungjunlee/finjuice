"""
Audit command: Inspect and manage audit logs.

Shows command execution history from .execution_audit.jsonl.
Useful for security review and debugging.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit,
    emit_error,
    error,
    success,
    warning,
)
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="audit",
    help="Inspect and manage audit logs",
)

TemplateDomain = Literal["asset", "transaction"]


@dataclass(frozen=True)
class TemplateMetrics:
    """Aggregated metrics for template_run events."""

    total: int
    success: int
    failed: int
    success_rate: float
    avg_duration: float
    retry_attempts: int
    retry_recovery: float


@dataclass(frozen=True)
class TemplateRunSummary:
    """Computed metrics and usage counters for template_run output rendering."""

    overall: TemplateMetrics
    asset: TemplateMetrics
    transaction: TemplateMetrics
    usage_counts: dict[str, int]
    domain_usage_counts: dict[TemplateDomain, dict[str, int]]


def _parse_duration(event: dict[str, Any]) -> float | None:
    """Parse duration value from audit event."""
    raw = event.get("duration")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid duration value in audit event: %r", raw)
        return None


def _compute_template_retry_stats(template_runs: list[dict[str, Any]]) -> tuple[int, int]:
    """Compute retry attempts and recovered retries from ordered template_run events.

    Retry attempt is counted when a failed run is immediately followed by another run
    with the same template_name and param_fingerprint.
    """
    retry_attempts = 0
    recovered_retries = 0
    for previous, current in zip(template_runs, template_runs[1:]):
        same_template = previous.get("template_name") == current.get("template_name")
        same_params = previous.get("param_fingerprint") == current.get("param_fingerprint")
        if same_template and same_params and previous.get("success") is False:
            retry_attempts += 1
            if current.get("success") is True:
                recovered_retries += 1
    return retry_attempts, recovered_retries


def _resolve_template_domain(event: dict[str, Any]) -> TemplateDomain:
    """Resolve template domain, falling back to a default when unset."""
    raw_domain = event.get("template_domain")
    if isinstance(raw_domain, str):
        normalized = raw_domain.strip().lower()
        if normalized in {"asset", "transaction"}:
            return cast(TemplateDomain, normalized)
        logger.debug(
            "Invalid template_domain value '%s'; falling back to template_name prefix",
            raw_domain,
        )

    template_name = str(event.get("template_name", ""))
    return "asset" if template_name.startswith("asset_") else "transaction"


def _compute_domain_template_retry_stats(
    template_runs: list[dict[str, Any]],
) -> dict[TemplateDomain, tuple[int, int]]:
    """Compute domain retry stats from the full ordered template event stream."""
    attempts: dict[TemplateDomain, int] = {"asset": 0, "transaction": 0}
    recovered: dict[TemplateDomain, int] = {"asset": 0, "transaction": 0}

    for previous, current in zip(template_runs, template_runs[1:]):
        same_template = previous.get("template_name") == current.get("template_name")
        same_params = previous.get("param_fingerprint") == current.get("param_fingerprint")
        if same_template and same_params and previous.get("success") is False:
            domain = _resolve_template_domain(previous)
            attempts[domain] += 1
            if current.get("success") is True:
                recovered[domain] += 1

    return {
        "asset": (attempts["asset"], recovered["asset"]),
        "transaction": (attempts["transaction"], recovered["transaction"]),
    }


def _count_template_outcomes(template_runs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Count total/success/failed outcomes from template events."""
    total = len(template_runs)
    success = sum(1 for event in template_runs if event.get("success") is True)
    failed = total - success
    return total, success, failed


def _compute_success_rate(success: int, total: int) -> float:
    """Compute success rate percentage."""
    return (success / total) * 100 if total > 0 else 0.0


def _compute_average_duration(template_runs: list[dict[str, Any]], total: int) -> float:
    """Compute average duration for template events."""
    if total == 0:
        return 0.0
    durations = [value for event in template_runs if (value := _parse_duration(event)) is not None]
    return sum(durations) / len(durations) if durations else 0.0


def _resolve_retry_stats(
    template_runs: list[dict[str, Any]],
    retry_stats: tuple[int, int] | None,
) -> tuple[int, int]:
    """Resolve retry stats from override or by computing from event stream."""
    return _compute_template_retry_stats(template_runs) if retry_stats is None else retry_stats


def _compute_retry_recovery_rate(retry_attempts: int, recovered_retries: int) -> float:
    """Compute retry recovery percentage."""
    return (recovered_retries / retry_attempts) * 100 if retry_attempts > 0 else 0.0


def _build_template_metrics(
    *,
    total: int,
    success: int,
    failed: int,
    avg_duration: float,
    retry_attempts: int,
    recovered_retries: int,
) -> TemplateMetrics:
    """Build TemplateMetrics from computed scalar values."""
    return TemplateMetrics(
        total=total,
        success=success,
        failed=failed,
        success_rate=_compute_success_rate(success, total),
        avg_duration=avg_duration,
        retry_attempts=retry_attempts,
        retry_recovery=_compute_retry_recovery_rate(retry_attempts, recovered_retries),
    )


def _compute_template_metrics(
    template_runs: list[dict[str, Any]],
    retry_stats: tuple[int, int] | None = None,
) -> TemplateMetrics:
    """Compute aggregate metrics for a template_run event group."""
    total, success, failed = _count_template_outcomes(template_runs)
    retry_attempts, recovered_retries = _resolve_retry_stats(template_runs, retry_stats)
    return _build_template_metrics(
        total=total,
        success=success,
        failed=failed,
        avg_duration=_compute_average_duration(template_runs, total),
        retry_attempts=retry_attempts,
        recovered_retries=recovered_retries,
    )


def _collect_template_usage(
    template_runs: list[dict[str, Any]],
) -> tuple[
    dict[TemplateDomain, list[dict[str, Any]]],
    dict[str, int],
    dict[TemplateDomain, dict[str, int]],
]:
    """Collect per-domain runs and usage counters in a single pass."""
    domain_runs: dict[TemplateDomain, list[dict[str, Any]]] = {"asset": [], "transaction": []}
    usage_counts: dict[str, int] = {}
    domain_usage_counts: dict[TemplateDomain, dict[str, int]] = {"asset": {}, "transaction": {}}
    for event in template_runs:
        template_name = str(event.get("template_name", "unknown"))
        usage_counts[template_name] = usage_counts.get(template_name, 0) + 1
        domain = _resolve_template_domain(event)
        domain_runs[domain].append(event)
        domain_usage = domain_usage_counts[domain]
        domain_usage[template_name] = domain_usage.get(template_name, 0) + 1
    return domain_runs, usage_counts, domain_usage_counts


def _build_domain_metrics(
    template_runs: list[dict[str, Any]],
    domain_runs: dict[TemplateDomain, list[dict[str, Any]]],
) -> tuple[TemplateMetrics, TemplateMetrics]:
    """Build domain-specific template metrics using global-adjacency retry attribution."""
    retry_stats = _compute_domain_template_retry_stats(template_runs)
    asset_metrics = _compute_template_metrics(
        domain_runs["asset"],
        retry_stats=retry_stats["asset"],
    )
    transaction_metrics = _compute_template_metrics(
        domain_runs["transaction"],
        retry_stats=retry_stats["transaction"],
    )
    return asset_metrics, transaction_metrics


def _summarize_template_runs(template_runs: list[dict[str, Any]]) -> TemplateRunSummary:
    """Compute template metrics and usage counters for rendering."""
    domain_runs, usage_counts, domain_usage_counts = _collect_template_usage(template_runs)
    asset_metrics, transaction_metrics = _build_domain_metrics(template_runs, domain_runs)
    return TemplateRunSummary(
        overall=_compute_template_metrics(template_runs),
        asset=asset_metrics,
        transaction=transaction_metrics,
        usage_counts=usage_counts,
        domain_usage_counts=domain_usage_counts,
    )


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


def _serialize_template_run_summary(summary: TemplateRunSummary) -> dict[str, Any]:
    """Serialize template metrics summary for JSON output."""
    return cast(dict[str, Any], asdict(summary))


def _read_audit_events_with_skip(audit_log_path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read JSONL events and skip malformed/non-object rows."""
    events: list[dict[str, Any]] = []
    skipped = 0
    with open(audit_log_path) as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as e:
                skipped += 1
                logger.warning("Skipping malformed audit line %d: %s", line_number, e)
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
            else:
                skipped += 1
                logger.warning("Skipping non-object audit line %d", line_number)
    return events, skipped


def _write_audit_events_atomically(audit_log_path: Path, events: list[dict[str, Any]]) -> None:
    """Write JSONL events to a temporary file and atomically replace target file."""
    temp_path = audit_log_path.with_suffix(f"{audit_log_path.suffix}.tmp")
    try:
        with open(temp_path, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        temp_path.replace(audit_log_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


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


@app.command()
def log(
    ctx: typer.Context,
    last_n: int = typer.Option(
        10,
        "--last",
        "-n",
        help="Show last N events (default: 10)",
    ),
    event_type: str = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by event type (e.g., command_suggested, command_executed)",
    ),
    failed_only: bool = typer.Option(
        False,
        "--failed",
        help="Show only failed executions",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Display audit log of command executions.

    Shows recent AI command suggestions, confirmations, and execution results.
    Useful for security review and debugging.

    Examples:
        # Show last 20 events
        finjuice audit log --last 20

        # Show only suggestions
        finjuice audit log --type command_suggested

        # Show only failed executions
        finjuice audit log --failed
    """
    config: Config = ctx.obj["config"]
    data_dir = config.data_dir
    audit_log_path = data_dir / ".execution_audit.jsonl"

    if not audit_log_path.exists():
        if json_output:
            emit_error(
                "No audit log found. Run audited finjuice commands to generate logs.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=True,
                command="audit log",
            )
        warning("No audit log found. Run audited finjuice commands to generate logs.")
        raise typer.Exit(1)

    # Read JSON Lines
    try:
        events, skipped = _read_audit_events_with_skip(audit_log_path)
    except OSError as e:
        if json_output:
            emit_error(
                f"Failed to read audit log: {e}",
                error_code=ErrorCode.FILE_ACCESS_ERROR,
                json_output=True,
                command="audit log",
            )
        error(f"Failed to read audit log: {e}")
        raise typer.Exit(1)

    if skipped > 0 and not json_output:
        warning(f"Skipped {skipped} malformed audit entries.")

    # Filter by event type
    if event_type:
        events = [e for e in events if e.get("event") == event_type]

    # Filter failed executions
    if failed_only:
        events = [
            e
            for e in events
            if e.get("event") in {"command_executed", "template_run"} and not e.get("success", True)
        ]

    # Get last N events
    events = events[-last_n:]

    result = {"events": events, "count": len(events), "skipped_entries": skipped}
    emit(result, json_output, _render_audit_log, command="audit log")


@app.command()
def stats(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Show audit log statistics.

    Displays summary of:
    - Total commands suggested/executed
    - Success/failure rates
    - Most common commands
    """
    config: Config = ctx.obj["config"]
    data_dir = config.data_dir
    audit_log_path = data_dir / ".execution_audit.jsonl"

    if not audit_log_path.exists():
        if json_output:
            emit_error(
                "No audit log found.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=True,
                command="audit stats",
            )
        warning("No audit log found.")
        raise typer.Exit(1)

    # Read all events
    try:
        events, skipped = _read_audit_events_with_skip(audit_log_path)
    except OSError as e:
        if json_output:
            emit_error(
                f"Failed to read audit log: {e}",
                error_code=ErrorCode.FILE_ACCESS_ERROR,
                json_output=True,
                command="audit stats",
            )
        error(f"Failed to read audit log: {e}")
        raise typer.Exit(1)

    if skipped > 0 and not json_output:
        warning(f"Skipped {skipped} malformed audit entries.")

    # Calculate statistics
    total_suggestions = sum(1 for e in events if e.get("event") == "command_suggested")
    confirmed = sum(
        1
        for e in events
        if e.get("event") == "command_suggested" and e.get("user_confirmed") is True
    )
    declined = sum(
        1
        for e in events
        if e.get("event") == "command_suggested" and e.get("user_confirmed") is False
    )

    total_executions = sum(1 for e in events if e.get("event") == "command_executed")
    successful = sum(
        1 for e in events if e.get("event") == "command_executed" and e.get("success") is True
    )
    failed = sum(
        1 for e in events if e.get("event") == "command_executed" and e.get("success") is False
    )

    # Most common commands
    command_counts: dict[str, int] = {}
    for event in events:
        if event.get("event") == "command_suggested":
            cmd = event.get("command", "unknown")
            command_counts[cmd] = command_counts.get(cmd, 0) + 1

    success_rate = (successful / total_executions) * 100 if total_executions > 0 else None
    result: dict[str, Any] = {
        "suggestions": {
            "total": total_suggestions,
            "confirmed": confirmed,
            "declined": declined,
        },
        "executions": {
            "total": total_executions,
            "successful": successful,
            "failed": failed,
        },
        "success_rate": success_rate,
        "top_commands": [
            {"command": cmd, "count": count}
            for cmd, count in sorted(command_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ],
        "skipped_entries": skipped,
    }

    template_runs = [e for e in events if e.get("event") == "template_run"]
    if template_runs:
        template_summary = _summarize_template_runs(template_runs)
        result["_template_summary"] = template_summary
        result["template_summary"] = _serialize_template_run_summary(template_summary)

    json_result = {k: v for k, v in result.items() if not k.startswith("_")}
    emit(json_result, json_output, lambda _: _render_audit_stats(result), command="audit stats")


@app.command()
def clear(
    ctx: typer.Context,
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Clear audit log (keep last 100 entries).

    Useful for housekeeping when log file grows large.
    Keeps last 100 entries for recent history.
    """
    config: Config = ctx.obj["config"]
    data_dir = config.data_dir
    audit_log_path = data_dir / ".execution_audit.jsonl"

    if not audit_log_path.exists():
        if json_output:
            emit_error(
                "No audit log found.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=True,
                command="audit clear",
            )
        warning("No audit log found.")
        return

    if not confirm:
        response = typer.confirm(
            "Clear audit log (keep last 100 entries)?",
            default=False,
            err=json_output,
        )
        if not response:
            if json_output:
                emit_error(
                    "Audit log clear cancelled by user.",
                    error_code=ErrorCode.USER_CANCELLED,
                    exit_code=ExitCode.USER_CANCELLED,
                    json_output=True,
                    command="audit clear",
                )
            console.print("Cancelled.")
            return

    try:
        events, skipped = _read_audit_events_with_skip(audit_log_path)
    except OSError as e:
        if json_output:
            emit_error(
                f"Failed to read audit log: {e}",
                error_code=ErrorCode.FILE_ACCESS_ERROR,
                json_output=True,
                command="audit clear",
            )
        error(f"Failed to read audit log: {e}")
        raise typer.Exit(1)

    if skipped > 0 and not json_output:
        warning(f"Skipped {skipped} malformed audit entries.")

    # Keep last 100
    events = events[-100:]

    try:
        _write_audit_events_atomically(audit_log_path, events)
    except OSError as e:
        if json_output:
            emit_error(
                f"Failed to rewrite audit log: {e}",
                error_code=ErrorCode.FILE_ACCESS_ERROR,
                json_output=True,
                command="audit clear",
            )
        error(f"Failed to rewrite audit log: {e}")
        raise typer.Exit(1)

    result = {"entries_kept": len(events), "action": "cleared", "skipped_entries": skipped}
    emit(result, json_output, _render_audit_clear, command="audit clear")
