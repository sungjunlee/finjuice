"""Transaction-metric aggregation helpers for ``finjuice status``.

Owns per-partition row/date/tagging/filter aggregation into
``_TransactionMetrics``. Fact orchestration stays in
:mod:`finjuice.pipeline.cli.commands.status.compute`, which re-exports
these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.storage.report_filter_exprs import matched_report_filter_rule_indexes
from finjuice.pipeline.tagging.models import ReportFilters

from .compute_helpers import (
    _add_untagged_merchants,
    _count_tagging_rows,
    _expand_date_range,
    _read_status_partition,
    _top_untagged_merchants,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TransactionMetrics:
    """Aggregated transaction metrics across CSV partitions."""

    total_rows: int
    min_date: Any | None
    max_date: Any | None
    untagged_count: int
    suggestable_untagged_count: int
    transfer_candidate_count: int
    transfer_excluded_count: int
    transfer_excluded_untagged_count: int
    unconfirmed_transfer_candidate_count: int
    untagged_merchants: list[dict[str, Any]]
    untagged_merchants_total: int
    filters_applied: int


def _collect_transaction_metrics(
    partitions: list[Path],
    report_filters: ReportFilters,
    report_filter_expr: pl.Expr | None,
    *,
    top_n: int,
) -> _TransactionMetrics:
    """Aggregate row, date, tagging, and filter metrics across partitions."""
    total_rows = 0
    min_date = None
    max_date = None
    untagged_count = 0
    suggestable_untagged_count = 0
    transfer_candidate_count = 0
    transfer_excluded_count = 0
    transfer_excluded_untagged_count = 0
    unconfirmed_transfer_candidate_count = 0
    untagged_merchants: dict[str, int] = {}
    matched_filter_indexes: set[int] = set()

    for partition_path in partitions:
        try:
            df = _read_status_partition(partition_path)
            matched_filter_indexes.update(matched_report_filter_rule_indexes(df, report_filters))
            if report_filter_expr is not None:
                df = df.filter(~report_filter_expr)

            total_rows += len(df)
            if len(df) == 0:
                continue

            min_date, max_date = _expand_date_range(df, min_date, max_date)
            row_metrics = _count_tagging_rows(df)
            untagged_count += row_metrics["untagged_count"]
            suggestable_untagged_count += row_metrics["suggestable_untagged_count"]
            transfer_candidate_count += row_metrics["transfer_candidate_count"]
            transfer_excluded_count += row_metrics["transfer_excluded_count"]
            transfer_excluded_untagged_count += row_metrics["transfer_excluded_untagged_count"]
            unconfirmed_transfer_candidate_count += row_metrics[
                "unconfirmed_transfer_candidate_count"
            ]
            _add_untagged_merchants(untagged_merchants, row_metrics["untagged"])
        except (OSError, pl.exceptions.ComputeError) as exc:
            logger.warning("Could not read %s: %s", partition_path, exc)

    untagged_merchant_list, untagged_merchants_total = _top_untagged_merchants(
        untagged_merchants,
        top_n=top_n,
    )
    return _TransactionMetrics(
        total_rows=total_rows,
        min_date=min_date,
        max_date=max_date,
        untagged_count=untagged_count,
        suggestable_untagged_count=suggestable_untagged_count,
        transfer_candidate_count=transfer_candidate_count,
        transfer_excluded_count=transfer_excluded_count,
        transfer_excluded_untagged_count=transfer_excluded_untagged_count,
        unconfirmed_transfer_candidate_count=unconfirmed_transfer_candidate_count,
        untagged_merchants=untagged_merchant_list,
        untagged_merchants_total=untagged_merchants_total,
        filters_applied=len(matched_filter_indexes),
    )
