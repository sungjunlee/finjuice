"""Audit stats payload helpers for ``finjuice audit stats``.

Owns suggestion/execution counting, top-command ranking, and template-run
summary attachment. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.audit`. JSONL I/O lives in
:mod:`finjuice.pipeline.cli.commands.audit_io`. Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.audit_rendering`. Template-run metric
math lives in :mod:`finjuice.pipeline.cli.commands.audit_template_metrics`.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.commands.audit_template_metrics import (
    _serialize_template_run_summary,
    _summarize_template_runs,
)


def _count_command_suggestions(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count command_suggested events by confirmation outcome."""
    total = sum(1 for event in events if event.get("event") == "command_suggested")
    confirmed = sum(
        1
        for event in events
        if event.get("event") == "command_suggested" and event.get("user_confirmed") is True
    )
    declined = sum(
        1
        for event in events
        if event.get("event") == "command_suggested" and event.get("user_confirmed") is False
    )
    return {"total": total, "confirmed": confirmed, "declined": declined}


def _count_command_executions(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count command_executed events by success outcome."""
    total = sum(1 for event in events if event.get("event") == "command_executed")
    successful = sum(
        1
        for event in events
        if event.get("event") == "command_executed" and event.get("success") is True
    )
    failed = sum(
        1
        for event in events
        if event.get("event") == "command_executed" and event.get("success") is False
    )
    return {"total": total, "successful": successful, "failed": failed}


def _build_top_commands(
    events: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Build the most common suggested-command counts."""
    command_counts: dict[str, int] = {}
    for event in events:
        if event.get("event") == "command_suggested":
            cmd = event.get("command", "unknown")
            command_counts[cmd] = command_counts.get(cmd, 0) + 1
    return [
        {"command": cmd, "count": count}
        for cmd, count in sorted(command_counts.items(), key=lambda item: item[1], reverse=True)[
            :limit
        ]
    ]


def _attach_template_run_summary(
    result: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    """Attach template-run metrics when template_run events are present."""
    template_runs = [event for event in events if event.get("event") == "template_run"]
    if not template_runs:
        return
    template_summary = _summarize_template_runs(template_runs)
    result["_template_summary"] = template_summary
    result["template_summary"] = _serialize_template_run_summary(template_summary)


def _build_audit_stats_result(
    events: list[dict[str, Any]],
    skipped: int,
) -> dict[str, Any]:
    """Assemble the audit stats payload used by human and JSON output."""
    suggestions = _count_command_suggestions(events)
    executions = _count_command_executions(events)
    success_rate = (
        (executions["successful"] / executions["total"]) * 100 if executions["total"] > 0 else None
    )
    result: dict[str, Any] = {
        "suggestions": suggestions,
        "executions": executions,
        "success_rate": success_rate,
        "top_commands": _build_top_commands(events),
        "skipped_entries": skipped,
    }
    _attach_template_run_summary(result, events)
    return result
