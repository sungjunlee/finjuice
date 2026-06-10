"""
CSV partition storage layer for transactions (Polars-only).

Provides year/month partitioned CSV storage optimized for:
- AI agent workflows (Claude Code Read/Edit tools)
- Token efficiency (56% less than JSON, 21x vs single file)
- Git trackability (line-oriented diffs)
- Human readability (grep, awk, csvkit compatible)

Backend:
    - Polars: 3-5x performance vs legacy pandas implementation
    - All functions use Polars DataFrames natively

Directory structure:
    data/transactions/
        2024/
            01/transactions.csv
            02/transactions.csv
            ...
        2025/
            01/transactions.csv
            ...

Each partition is sorted by datetime for stable diffs.
"""

from finjuice.pipeline.storage.csv_assets import (
    append_asset_snapshots,
    read_asset_snapshot_month,
    write_asset_snapshot_month,
)
from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_COLUMNS,
    ASSET_SNAPSHOT_POLARS_SCHEMA,
    CSV_COLUMNS,
    POLARS_SCHEMA,
    get_asset_snapshot_partition_path,
    get_partition_path,
)
from finjuice.pipeline.storage.csv_transactions import (
    append_transactions,
    find_transaction_by_hash,
    get_all_transactions,
    read_month,
    read_range,
    upsert_transaction,
    write_month,
)

__all__ = [
    "CSV_COLUMNS",
    "POLARS_SCHEMA",
    "ASSET_SNAPSHOT_COLUMNS",
    "ASSET_SNAPSHOT_POLARS_SCHEMA",
    "get_partition_path",
    "get_asset_snapshot_partition_path",
    "read_month",
    "read_asset_snapshot_month",
    "read_range",
    "write_month",
    "write_asset_snapshot_month",
    "append_transactions",
    "append_asset_snapshots",
    "upsert_transaction",
    "find_transaction_by_hash",
    "get_all_transactions",
]
