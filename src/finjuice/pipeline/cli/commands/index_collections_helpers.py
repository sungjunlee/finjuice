"""Filesystem counting helpers for ``finjuice index`` collections.

Owns ISO mtimes, YAML list/signal counts, and CSV row counts without
exposing file contents. Collection specs, catalog entries, and
per-collection builders stay in
:mod:`finjuice.pipeline.cli.commands.index_collections`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import yaml


def _iso_mtime(path: Path) -> str | None:
    """Return a stable ISO timestamp for a file or directory mtime."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _latest_mtime(paths: list[Path]) -> str | None:
    """Return the latest mtime across existing paths."""
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    latest = max(path.stat().st_mtime for path in existing)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _safe_yaml_count(path: Path, key: str) -> int | None:
    """Count top-level YAML list entries without exposing their contents."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    values = payload.get(key) if isinstance(payload, dict) else None
    return len(values) if isinstance(values, list) else 0


def _yaml_signal_count(path: Path, keys: tuple[str, ...]) -> int | None:
    """Count configured YAML sections and list entries without exposing values."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return 0

    count = 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1 if value else 0
        elif value not in (None, ""):
            count += 1
    return count


def _csv_row_count(paths: list[Path]) -> int | None:
    """Count CSV rows without materializing row content into the output."""
    total = 0
    for path in paths:
        try:
            total += pl.scan_csv(path).select(pl.len()).collect().item()
        except (OSError, pl.exceptions.ComputeError):
            return None
    return total
