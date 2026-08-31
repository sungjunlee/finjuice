"""Review JSON payload shaping helpers.

Owns the review payload post-processing contract: deterministic row ordering,
rule-note loading, and count reconciliation after JSON byte truncation.
Filter predicates live in :mod:`finjuice.pipeline.cli.commands.review_filters`,
row projection in :mod:`finjuice.pipeline.cli.commands.review_serialize`, and
human rendering in :mod:`finjuice.pipeline.cli.commands.review_rendering`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.tagging.rules_yaml_io import summarize_rule_notes

__all__ = [
    "_load_review_rule_notes",
    "_sort_review_rows",
    "_sync_review_page_counts",
]


def _load_review_rule_notes(rules_file: Path) -> list[dict[str, Any]]:
    """Best-effort rule notes for review JSON output."""
    try:
        return summarize_rule_notes(rules_file, limit=5)
    except (OSError, ValueError):
        return []


def _sort_review_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Sort review rows newest-first with a stable row_hash tie-breaker."""
    sort_columns = [column for column in ("datetime", "date", "row_hash") if column in df.columns]
    if not sort_columns:
        return df
    descending = [column != "row_hash" for column in sort_columns]
    return df.sort(sort_columns, descending=descending)


def _sync_review_page_counts(payload: dict[str, Any]) -> None:
    """Keep count fields aligned after JSON byte truncation."""
    returned_count = len(payload.get("transactions", []))
    payload["total_count"] = returned_count
    payload.pop("row_count", None)

    signals = payload.get("signals")
    if isinstance(signals, dict):
        signals["returned_count"] = returned_count
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            signals["truncated"] = bool(pagination.get("has_more", False))
