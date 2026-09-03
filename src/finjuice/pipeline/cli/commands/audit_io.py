"""JSONL audit-log I/O helpers for ``finjuice audit``.

Owns reading JSONL events while skipping malformed/non-object rows, and
atomic rewrite of the audit log. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.audit`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
