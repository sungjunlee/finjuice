"""SQLite-backed status fact inputs for the ``finjuice status`` read path.

Projections the transaction frame from the authoritative SQLite repository
(#436 read-compatibility slice) and derives the partition-equivalent inputs
``collect_status_facts`` assembles into :class:`StatusFacts`. Fact assembly,
diagnosis, and rendering stay in the existing status modules so human and
JSON output contracts are unchanged.

TODO(#436 follow-up): the ``--detailed`` insights snapshot still reads CSV
partitions through :mod:`finjuice.pipeline.insights`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import polars as pl

from finjuice.pipeline.query import distinct_month_count, read_transactions_frame
from finjuice.pipeline.storage.schema_registry import (
    PartitionSchemaSummary,
    summarize_partition_schema_versions,
)

from .compute_helpers import _normalize_status_partition_schema


@dataclass(frozen=True)
class SqliteStatusInputs:
    """Partition-equivalent status inputs projected from one SQLite snapshot."""

    frame: pl.DataFrame
    partition_count: int
    schema_summary: PartitionSchemaSummary


def load_sqlite_status_inputs(database: Path, *, metadata_dir: Path) -> SqliteStatusInputs:
    """Project repository transactions into status fact inputs.

    Args:
        database: Path to the published ``finjuice.sqlite3`` repository file.
        metadata_dir: Data-directory metadata folder used for schema registry
            context, mirroring the CSV partition summary inputs.

    Returns:
        Normalized transaction frame plus partition-count and schema-summary
        equivalents for the same data.
    """
    frame = _normalize_status_partition_schema(read_transactions_frame(database))
    partition_count = distinct_month_count(frame)
    base_summary = summarize_partition_schema_versions([], metadata_dir=metadata_dir)
    schema_summary = replace(
        base_summary,
        partition_count=partition_count,
        active_versions=(base_summary.current_version,) if partition_count > 0 else (),
    )
    return SqliteStatusInputs(
        frame=frame,
        partition_count=partition_count,
        schema_summary=schema_summary,
    )


__all__ = ["SqliteStatusInputs", "load_sqlite_status_inputs"]
