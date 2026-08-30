"""
Audit command: Inspect and manage audit logs.

Shows command execution history from .execution_audit.jsonl.
Useful for security review and debugging.

Human rendering lives in :mod:`finjuice.pipeline.cli.commands.audit_rendering`.
JSONL I/O lives in :mod:`finjuice.pipeline.cli.commands.audit_io` and is
re-exported here so existing callers can keep importing from this module.
"""

from typing import Any

import typer

from finjuice.pipeline.cli.commands.audit_io import (
    _read_audit_events_with_skip,
    _write_audit_events_atomically,
)
from finjuice.pipeline.cli.commands.audit_rendering import (
    _render_audit_clear,
    _render_audit_log,
    _render_audit_stats,
)
from finjuice.pipeline.cli.commands.audit_template_metrics import (
    _serialize_template_run_summary,
    _summarize_template_runs,
)
from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit,
    emit_error,
    error,
    warning,
)
from finjuice.pipeline.config import Config

app = typer.Typer(
    name="audit",
    help="Inspect and manage audit logs",
)


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
