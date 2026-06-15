"""
Partition deduplication and preview logic.

Provides read-only preview of what would be inserted into transaction and asset
snapshot partitions, using cached existing-hash lookups.
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


def _get_partition_hashes(
    csv_base_dir: Path,
    year: int,
    month: int,
    cache: dict[tuple[int, int], set[str]],
) -> set[str]:
    """Load and cache existing row hashes for a transaction partition."""
    key = (year, month)
    if key not in cache:
        existing_df = csv_partition.read_month(
            csv_base_dir,
            year,
            month,
            columns=["row_hash"],
            parse_tags=False,
        )
        if "row_hash" in existing_df.columns:
            cache[key] = {
                str(value)
                for value in existing_df.get_column("row_hash").drop_nulls().to_list()
                if value
            }
        else:
            cache[key] = set()
    return cache[key]


def _get_asset_snapshot_keys(
    asset_base_dir: Path,
    year: int,
    month: int,
    cache: dict[tuple[int, int], set[tuple[str, str, str]]],
) -> set[tuple[str, str, str]]:
    """Load and cache existing asset snapshot dedup keys for a partition."""
    key = (year, month)
    if key not in cache:
        existing_df = csv_partition.read_asset_snapshot_month(
            asset_base_dir,
            year,
            month,
            columns=["snapshot_date", "account_id", "instrument_id"],
        )
        if existing_df.height == 0:
            cache[key] = set()
        else:
            cache[key] = {
                (
                    str(snapshot_date),
                    str(account_id),
                    str(instrument_id),
                )
                for snapshot_date, account_id, instrument_id in existing_df.select(
                    ["snapshot_date", "account_id", "instrument_id"]
                ).iter_rows()
            }
    return cache[key]


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


def _preview_append_transactions(
    csv_base_dir: Path,
    df: Any,
    cache: dict[tuple[int, int], set[str]],
) -> dict[str, Any]:
    """Preview transaction partition writes without touching the filesystem."""
    if df.height == 0:
        return {"rows_inserted": 0, "rows_skipped": 0, "affected_partitions": []}

    rows_inserted = 0
    rows_skipped = 0
    affected_partitions: list[str] = []
    grouped_hashes: dict[tuple[int, int], list[str]] = {}

    for date_str, row_hash in df.select(["date", "row_hash"]).iter_rows():
        year = int(str(date_str)[:4])
        month = int(str(date_str)[5:7])
        grouped_hashes.setdefault((year, month), []).append(str(row_hash))

    for (year, month), row_hashes in grouped_hashes.items():
        seen_in_batch: set[str] = set()
        existing_hashes = _get_partition_hashes(csv_base_dir, year, month, cache)
        partition_inserted = 0

        for row_hash in row_hashes:
            if row_hash in seen_in_batch:
                rows_skipped += 1
                continue

            seen_in_batch.add(row_hash)

            if row_hash in existing_hashes:
                rows_skipped += 1
                continue

            existing_hashes.add(row_hash)
            rows_inserted += 1
            partition_inserted += 1

        if partition_inserted > 0:
            affected_partitions.append(
                str(csv_partition.get_partition_path(csv_base_dir, year, month))
            )

    return {
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
        "affected_partitions": sorted(affected_partitions),
    }


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


def _preview_append_asset_snapshots(
    asset_base_dir: Path,
    df: Any,
    cache: dict[tuple[int, int], set[tuple[str, str, str]]],
) -> dict[str, Any]:
    """Preview asset snapshot partition writes without touching the filesystem."""
    if df.height == 0:
        return {"rows_inserted": 0, "rows_skipped": 0, "affected_partitions": []}

    rows_inserted = 0
    rows_skipped = 0
    affected_partitions: list[str] = []
    grouped_keys: dict[tuple[int, int], list[tuple[str, str, str]]] = {}

    for snapshot_date, account_id, instrument_id in df.select(
        ["snapshot_date", "account_id", "instrument_id"]
    ).iter_rows():
        snapshot_date_str = str(snapshot_date)
        year = int(snapshot_date_str[:4])
        month = int(snapshot_date_str[5:7])
        grouped_keys.setdefault((year, month), []).append(
            (snapshot_date_str, str(account_id), str(instrument_id))
        )

    for (year, month), dedup_keys in grouped_keys.items():
        seen_in_batch: set[tuple[str, str, str]] = set()
        existing_keys = _get_asset_snapshot_keys(asset_base_dir, year, month, cache)
        partition_inserted = 0

        for dedup_key in dedup_keys:
            if dedup_key in seen_in_batch:
                rows_skipped += 1
                continue

            seen_in_batch.add(dedup_key)

            if dedup_key in existing_keys:
                rows_skipped += 1
                continue

            existing_keys.add(dedup_key)
            rows_inserted += 1
            partition_inserted += 1

        if partition_inserted > 0:
            affected_partitions.append(
                str(csv_partition.get_asset_snapshot_partition_path(asset_base_dir, year, month))
            )

    return {
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
        "affected_partitions": sorted(affected_partitions),
    }
