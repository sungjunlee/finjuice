"""
Partition deduplication and preview logic.

Provides read-only preview of what would be inserted into transaction and asset
snapshot partitions, using cached existing-hash lookups.
"""

from pathlib import Path
from typing import Any

from ..storage import csv_partition


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
