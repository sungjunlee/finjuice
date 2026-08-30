"""Schema version detection for CSV partition storage.

Owns compatible-read inference, partition schema summaries, and the public
detection API. Header matching helpers live in
:mod:`finjuice.pipeline.storage.schema_detect_helpers` and are re-exported
here so existing callers can keep importing from this module.

Registry load and cache stay in
:mod:`finjuice.pipeline.storage.schema_registry`, which re-exports this
public API so existing callers can keep importing from that module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

import yaml

from finjuice.pipeline.storage.schema_detect_helpers import (
    _header_matches_schema,  # noqa: F401 — re-exported for schema_registry
    _infer_read_compatible_legacy_version,
    _missing_read_compatible_columns,
    _read_csv_header,
    _schema_columns,
)


class SchemaCompatibilityState(str, Enum):
    """Compatibility state for a detected transaction partition schema."""

    ACTIVE = "active"
    COMPATIBLE_LEGACY = "compatible-legacy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SchemaDetection:
    """Detected schema metadata for a single CSV partition."""

    csv_path: Path
    header: tuple[str, ...]
    version: int | None
    state: SchemaCompatibilityState
    current_version: int
    schema_key: str | None = None
    reason: str | None = None

    @property
    def is_supported(self) -> bool:
        """Return whether the current runtime can safely read this schema."""
        return self.state in {
            SchemaCompatibilityState.ACTIVE,
            SchemaCompatibilityState.COMPATIBLE_LEGACY,
        }

    @property
    def is_legacy(self) -> bool:
        """Return whether the partition is readable but not the active write schema."""
        return self.state is SchemaCompatibilityState.COMPATIBLE_LEGACY


@dataclass(frozen=True)
class PartitionSchemaSummary:
    """Aggregate schema compatibility state for a set of transaction partitions."""

    state: SchemaCompatibilityState
    current_version: int
    partition_count: int
    active_versions: tuple[int, ...]
    compatible_legacy_versions: tuple[int, ...]
    unsupported_versions: tuple[int | None, ...]
    unsupported_count: int

    @property
    def has_compatible_legacy(self) -> bool:
        """Return whether any partition uses a compatible inactive schema."""
        return bool(self.compatible_legacy_versions)

    @property
    def has_unsupported(self) -> bool:
        """Return whether any partition uses an unsupported or unknown schema."""
        return self.unsupported_count > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary to a JSON-safe payload."""
        return {
            "state": self.state.value,
            "current_version": self.current_version,
            "partition_count": self.partition_count,
            "active_versions": list(self.active_versions),
            "compatible_legacy_versions": list(self.compatible_legacy_versions),
            "unsupported_versions": list(self.unsupported_versions),
            "unsupported_count": self.unsupported_count,
        }


def _load_runtime_registry(metadata_dir: Path | None) -> dict[str, Any]:
    """Load the packaged runtime registry used for compatibility decisions."""
    from finjuice.pipeline.storage.schema_registry import _load_registry_for_detection

    return _load_registry_for_detection(metadata_dir)


def _load_local_registry_for_header_matching(metadata_dir: Path | None) -> dict[str, Any] | None:
    """Load a data-dir registry only as a supplemental source of legacy headers."""
    from finjuice.pipeline.storage.schema_registry import (
        _get_default_metadata_dir,
        load_schema_registry,
    )

    if metadata_dir is None:
        metadata_dir = _get_default_metadata_dir()

    if not (metadata_dir / "schema.yaml").exists():
        return None

    try:
        return load_schema_registry(metadata_dir)
    except (OSError, ValueError, yaml.YAMLError):
        return None


def _iter_schema_definitions_for_detection(
    runtime_registry: dict[str, Any],
    metadata_dir: Path | None,
) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield packaged schemas first, then local-only schemas for header identification."""
    seen_schema_keys: set[str] = set()
    runtime_schemas = cast(dict[str, Any], runtime_registry["schemas"])

    for version_key, schema_def_raw in runtime_schemas.items():
        seen_schema_keys.add(version_key)
        yield version_key, cast(dict[str, Any], schema_def_raw)

    local_registry = _load_local_registry_for_header_matching(metadata_dir)
    if local_registry is None:
        return

    local_schemas = cast(dict[str, Any], local_registry["schemas"])
    for version_key, schema_def_raw in local_schemas.items():
        if version_key in seen_schema_keys:
            continue
        yield version_key, cast(dict[str, Any], schema_def_raw)


def _version_number(version_key: str) -> int:
    """Extract the integer version from a registry key such as ``v3``."""
    return int(version_key.lstrip("v"))


def _compatible_read_versions(registry: dict[str, Any]) -> set[int]:
    """Return schema versions the active runtime declares as readable."""
    current_version = int(registry["current_version"])
    compatible_versions: set[int] = {current_version}

    compatibility = registry.get("compatibility", {})
    current_compatibility = compatibility.get(f"v{current_version}", {})
    can_read = current_compatibility.get("can_read")
    if can_read:
        compatible_versions.update(int(version) for version in can_read)
        return compatible_versions

    minimum_compatible_version = registry.get("minimum_compatible_version")
    if minimum_compatible_version is not None:
        compatible_versions.update(range(int(minimum_compatible_version), current_version + 1))

    return compatible_versions


def get_compatible_read_versions(metadata_dir: Path | None = None) -> set[int]:
    """Return schema versions the active runtime can read."""
    return _compatible_read_versions(_load_runtime_registry(metadata_dir))


def detect_schema_version(csv_path: Path, metadata_dir: Path | None = None) -> SchemaDetection:
    """
    Detect the schema compatibility state from a CSV file structure.

    Detection strategy:
    1. Read CSV header row
    2. Match column count and names against all known schemas, including inactive schemas
    3. Classify as active, compatible-legacy, or unsupported

    Args:
        csv_path: Path to CSV partition file
        metadata_dir: Path to metadata directory (default: data/metadata)

    Returns:
        SchemaDetection containing version and compatibility state

    Raises:
        FileNotFoundError: If the CSV file does not exist
        ValueError: If the CSV file is empty

    Example:
        >>> from pathlib import Path
        >>> csv_path = Path('data/transactions/2025/07/transactions.csv')
        >>> detection = detect_schema_version(csv_path)
        >>> print(detection.state.value)
        active
    """
    header = _read_csv_header(csv_path)
    registry = _load_runtime_registry(metadata_dir)
    current_version = int(registry["current_version"])
    compatible_versions = _compatible_read_versions(registry)

    schema_definitions = tuple(_iter_schema_definitions_for_detection(registry, metadata_dir))

    for version_key, schema_def in schema_definitions:
        if header != _schema_columns(schema_def):
            continue

        version_num = _version_number(version_key)
        if version_num == current_version and schema_def.get("active"):
            state = SchemaCompatibilityState.ACTIVE
            reason = "matches active schema"
        elif version_num in compatible_versions and version_num < current_version:
            state = SchemaCompatibilityState.COMPATIBLE_LEGACY
            reason = "matches inactive schema readable by the active runtime"
        else:
            state = SchemaCompatibilityState.UNSUPPORTED
            reason = "matches a schema version outside the active compatibility window"

        return SchemaDetection(
            csv_path=csv_path,
            header=header,
            version=version_num,
            state=state,
            current_version=current_version,
            schema_key=version_key,
            reason=reason,
        )

    for version_key, schema_def in schema_definitions:
        missing_columns = _missing_read_compatible_columns(header, schema_def)
        if not missing_columns:
            continue

        version_num = _version_number(version_key)
        if version_num == current_version and schema_def.get("active"):
            inferred_version = _infer_read_compatible_legacy_version(
                current_version=current_version,
                missing_columns=missing_columns,
            )
            if inferred_version in compatible_versions and inferred_version < current_version:
                return SchemaDetection(
                    csv_path=csv_path,
                    header=header,
                    version=inferred_version,
                    state=SchemaCompatibilityState.COMPATIBLE_LEGACY,
                    current_version=current_version,
                    schema_key=version_key,
                    reason="matches active schema with readable additive legacy columns missing",
                )

        if version_num not in compatible_versions:
            continue

        return SchemaDetection(
            csv_path=csv_path,
            header=header,
            version=version_num,
            state=SchemaCompatibilityState.COMPATIBLE_LEGACY,
            current_version=current_version,
            schema_key=version_key,
            reason="matches readable schema with additive legacy columns missing",
        )

    return SchemaDetection(
        csv_path=csv_path,
        header=header,
        version=None,
        state=SchemaCompatibilityState.UNSUPPORTED,
        current_version=current_version,
        schema_key=None,
        reason="header does not match any known transaction schema",
    )


def get_schema_version(csv_path: Path, metadata_dir: Path | None = None) -> int:
    """
    Auto-detect schema version from CSV file structure.

    Compatible inactive legacy schemas return their version number so callers
    that only need read compatibility continue to work. Use
    ``detect_schema_version()`` when the caller needs active vs legacy vs
    unsupported state.
    """
    detection = detect_schema_version(csv_path, metadata_dir)
    if detection.is_supported and detection.version is not None:
        return detection.version

    raise ValueError(
        f"Could not detect schema version for {csv_path}. "
        f"Header has {len(detection.header)} columns: {list(detection.header[:3])}..."
    )


def summarize_partition_schema_versions(
    partitions: Iterable[Path],
    metadata_dir: Path | None = None,
) -> PartitionSchemaSummary:
    """Summarize schema compatibility across transaction partition CSV files."""
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


__all__ = [
    "PartitionSchemaSummary",
    "SchemaCompatibilityState",
    "SchemaDetection",
    "detect_schema_version",
    "get_compatible_read_versions",
    "get_schema_version",
    "summarize_partition_schema_versions",
]
