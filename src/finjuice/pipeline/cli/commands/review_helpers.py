"""Review data-loading and next-step helpers.

Owns latest-month and all-history partition loading, plus additive
next-step cues for agent consumers. Filter predicates live in
:mod:`finjuice.pipeline.cli.commands.review_filters`, JSON row
projection in :mod:`finjuice.pipeline.cli.commands.review_serialize`,
payload shaping in :mod:`finjuice.pipeline.cli.commands.review_payload`,
and human rendering in :mod:`finjuice.pipeline.cli.commands.review_rendering`.
The Typer command stays in :mod:`finjuice.pipeline.cli.commands.review`,
which re-exports these names so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import polars as pl

__all__ = [
    "_build_review_next_steps",
    "_load_all_history",
    "_load_latest_month",
]


def _load_latest_month(csv_base_dir: Path) -> tuple[Optional[pl.DataFrame], Optional[str]]:
    """Load the most recent transaction month from CSV partitions."""
    from finjuice.pipeline.storage.csv_transactions import read_month

    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None, None

    latest = partitions[-1]
    year = int(latest.parts[-3])
    month = int(latest.parts[-2])
    month_label = f"{year:04d}-{month:02d}"

    return read_month(csv_base_dir, year, month), month_label


def _load_all_history(csv_base_dir: Path) -> Optional[pl.DataFrame]:
    """Load every transaction partition for all-history review mode."""
    from finjuice.pipeline.storage.csv_transactions import get_all_transactions

    partitions = sorted(csv_base_dir.glob("*/*/transactions.csv"))
    if not partitions:
        return None

    return get_all_transactions(csv_base_dir)


def _build_review_next_steps(
    *,
    month_label: str | None,
    all_history: bool,
    untagged: bool,
    low_confidence: float | None,
    untagged_count: int,
    limit: int,
    next_cursor: str | None,
    matched_count: int,
) -> list[dict[str, str]]:
    """Return additive next-step cues for agent consumers."""
    if matched_count == 0:
        return []

    steps: list[dict[str, str]] = []
    active_filters: list[str] = []
    if untagged:
        active_filters.append("--untagged")
    if all_history:
        active_filters.append("--all-history")
    elif month_label:
        active_filters.extend(["--month", month_label])
    if low_confidence is not None:
        active_filters.extend(["--low-confidence", str(low_confidence)])
    current_filter_suffix = f" {' '.join(active_filters)}" if active_filters else ""

    if untagged_count > 0 and not untagged:
        untagged_filter_suffix = " --untagged"
        if active_filters:
            untagged_filter_suffix += f" {' '.join(active_filters)}"
        steps.append(
            {
                "signal": "untagged_transactions",
                "message": "Focus on empty-tag rows first.",
                "command": f"finjuice review --json{untagged_filter_suffix}",
            }
        )

    if next_cursor is not None:
        steps.append(
            {
                "signal": "truncated_queue",
                "message": "Fetch the next page of the review queue.",
                "command": (
                    f"finjuice review --json{current_filter_suffix} "
                    f"--limit {limit} --cursor {next_cursor}"
                ),
            }
        )

    return steps
