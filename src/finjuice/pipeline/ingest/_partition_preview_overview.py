"""
Banksalad overview partition preview helpers.

Provides read-only preview of what would be inserted into Banksalad overview
CSV partitions, using cached existing dedup-key lookups. Extracted from
:mod:`finjuice.pipeline.ingest._partition_preview`, which re-exports these
names so existing callers can keep importing from that module.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from ..storage import csv_partition


@dataclass(frozen=True)
class _OverviewPreviewSpec:
    dedup_key: list[str]
    read_month: Any
    path_builder: Any
    partition_column: str


def _get_overview_keys(
    base_dir: Path,
    year: int,
    month: int,
    cache: dict[tuple[int, int], set[tuple[object, ...]]],
    spec: _OverviewPreviewSpec,
) -> set[tuple[object, ...]]:
    """Load and cache existing Banksalad overview dedup keys for a partition."""
    key = (year, month)
    if key not in cache:
        existing_df = spec.read_month(base_dir, year, month, columns=spec.dedup_key)
        if existing_df.height == 0:
            cache[key] = set()
        else:
            cache[key] = {tuple(row) for row in existing_df.select(spec.dedup_key).iter_rows()}
    return cache[key]


def _preview_append_banksalad_overview_table(
    base_dir: Path,
    df: Any,
    cache: dict[tuple[int, int], set[tuple[object, ...]]],
    spec: _OverviewPreviewSpec,
) -> dict[str, Any]:
    """Preview Banksalad overview table writes without touching the filesystem."""
    if df.height == 0:
        return {"rows_inserted": 0, "rows_skipped": 0, "affected_partitions": []}

    rows_inserted = 0
    rows_skipped = 0
    affected_partitions: list[str] = []
    grouped_keys: dict[tuple[int, int], list[tuple[object, ...]]] = {}
    selected_columns = list(dict.fromkeys([spec.partition_column, *spec.dedup_key]))

    for row in df.select(selected_columns).iter_rows(named=True):
        year, month = _partition_year_month(str(row[spec.partition_column]))
        grouped_keys.setdefault((year, month), []).append(tuple(row[col] for col in spec.dedup_key))

    for (year, month), dedup_keys in grouped_keys.items():
        seen_in_batch: set[tuple[object, ...]] = set()
        existing_keys = _get_overview_keys(base_dir, year, month, cache, spec)
        partition_inserted = 0

        for dedup_tuple in dedup_keys:
            if dedup_tuple in seen_in_batch:
                rows_skipped += 1
                continue

            seen_in_batch.add(dedup_tuple)

            if dedup_tuple in existing_keys:
                rows_skipped += 1
                continue

            existing_keys.add(dedup_tuple)
            rows_inserted += 1
            partition_inserted += 1

        if partition_inserted > 0:
            affected_partitions.append(str(spec.path_builder(base_dir, year, month)))

    return {
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
        "affected_partitions": sorted(affected_partitions),
    }


def _preview_append_banksalad_cashflow(
    base_dir: Path,
    df: Any,
    cache: dict[tuple[int, int], set[tuple[object, ...]]],
) -> dict[str, Any]:
    """Preview Banksalad cashflow writes using period-month partitioning."""
    if df.height == 0:
        return {"rows_inserted": 0, "rows_skipped": 0, "affected_partitions": []}

    partitioned_df = df.with_columns(
        pl.when(pl.col("period_month").is_not_null() & (pl.col("period_month") != ""))
        .then(pl.col("period_month"))
        .otherwise(pl.col("snapshot_date").str.slice(0, 7))
        .alias("_partition_source")
    )
    return _preview_append_banksalad_overview_table(
        base_dir,
        partitioned_df,
        cache,
        _OverviewPreviewSpec(
            dedup_key=csv_partition.BANKSALAD_CASHFLOW_DEDUP_KEY,
            read_month=csv_partition.read_banksalad_cashflow_month,
            path_builder=csv_partition.get_banksalad_cashflow_partition_path,
            partition_column="_partition_source",
        ),
    )


def _partition_year_month(partition_source: str) -> tuple[int, int]:
    """Return year/month from a YYYY-MM or YYYY-MM-DD partition source."""
    return int(partition_source[:4]), int(partition_source[5:7])
