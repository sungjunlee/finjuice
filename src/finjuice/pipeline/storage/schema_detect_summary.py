"""Partition schema-version summaries for CSV storage.

Owns aggregate compatibility state across transaction partition CSV files.
Single-file detection stays in
:mod:`finjuice.pipeline.storage.schema_detect`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finjuice.pipeline.storage.schema_detect import PartitionSchemaSummary


def summarize_partition_schema_versions(
    partitions: Iterable[Path],
    metadata_dir: Path | None = None,
) -> PartitionSchemaSummary:
    """Summarize schema compatibility across transaction partition CSV files."""
    from finjuice.pipeline.storage.schema_detect import (
        PartitionSchemaSummary,
        SchemaCompatibilityState,
        _load_runtime_registry,
        detect_schema_version,
    )

    registry = _load_runtime_registry(metadata_dir)
    current_version = int(registry["current_version"])

    active_versions: set[int] = set()
    compatible_legacy_versions: set[int] = set()
    unsupported_versions: set[int | None] = set()
    unsupported_count = 0
    partition_count = 0

    for partition_path in partitions:
        partition_count += 1
        try:
            detection = detect_schema_version(partition_path, metadata_dir)
        except (OSError, ValueError):
            unsupported_versions.add(None)
            unsupported_count += 1
            continue

        if detection.state is SchemaCompatibilityState.ACTIVE and detection.version is not None:
            active_versions.add(detection.version)
        elif (
            detection.state is SchemaCompatibilityState.COMPATIBLE_LEGACY
            and detection.version is not None
        ):
            compatible_legacy_versions.add(detection.version)
        else:
            unsupported_versions.add(detection.version)
            unsupported_count += 1

    if unsupported_count > 0:
        state = SchemaCompatibilityState.UNSUPPORTED
    elif compatible_legacy_versions:
        state = SchemaCompatibilityState.COMPATIBLE_LEGACY
    else:
        state = SchemaCompatibilityState.ACTIVE

    return PartitionSchemaSummary(
        state=state,
        current_version=current_version,
        partition_count=partition_count,
        active_versions=tuple(sorted(active_versions)),
        compatible_legacy_versions=tuple(sorted(compatible_legacy_versions)),
        unsupported_versions=tuple(sorted(unsupported_versions, key=lambda version: version or -1)),
        unsupported_count=unsupported_count,
    )
