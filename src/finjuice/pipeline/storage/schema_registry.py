"""
Schema registry for CSV partition storage.

Provides programmatic access to schema definitions, migration history,
and column validation. Header matching and compatible-read detection live
in :mod:`finjuice.pipeline.storage.schema_detect` and are re-exported here
so existing callers can keep importing from this module.

Load/cache helpers live in
:mod:`finjuice.pipeline.storage.schema_registry_helpers` and are re-exported
here so existing callers can keep importing from this module.

Migration guidance and CSV column-name validation live in
:mod:`finjuice.pipeline.storage.schema_registry_cluster` and are re-exported
here so existing callers can keep importing from this module.

Thread Safety:
    - load_schema_registry() is thread-safe via double-checked locking pattern
    - Safe for use in multi-threaded environments (web servers, parallel tests)
    - Cache is cleared automatically when metadata_dir changes
    - Manual cache clear: clear_cache()

Caching:
    - Schema loaded once per metadata_dir path
    - Cache hit: ~0.27 μs (instant, no I/O)
    - Cache miss: ~24 ms (file I/O + YAML parsing)
    - Speedup: ~87,780x on cache hit

Example:
    >>> from pathlib import Path
    >>> schema = load_schema_registry(Path("data/metadata"))
    >>> print(schema["current_version"])
    2

    >>> # Clear cache (useful in tests or after schema modification)
    >>> clear_cache()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from finjuice.pipeline.storage.schema_detect import (
    PartitionSchemaSummary,
    SchemaCompatibilityState,
    SchemaDetection,
    detect_schema_version,
    get_compatible_read_versions,
    get_schema_version,
    summarize_partition_schema_versions,
)
from finjuice.pipeline.storage.schema_registry_cluster import (
    get_schema_migration_guidance,
    validate_column_names,
)
from finjuice.pipeline.storage.schema_registry_helpers import (
    _get_default_metadata_dir,
    _load_registry_for_detection,  # noqa: F401 — re-exported for existing schema_registry imports
    clear_cache,
    load_schema_registry,
)


def get_current_schema(metadata_dir: Path | None = None) -> dict[str, Any]:
    """
    Get current active schema definition.

    Args:
        metadata_dir: Path to metadata directory (default: data/metadata)

    Returns:
        Current schema definition dict

    Example:
        >>> schema = get_current_schema()
        >>> columns = schema['partition_schema']['columns']
        >>> print(f"Current schema has {len(columns)} columns")
        Current schema has 24 columns
    """
    if metadata_dir is None:
        # Use environment variable or CWD-relative path (Issue #62)
        metadata_dir = _get_default_metadata_dir()

    registry = load_schema_registry(metadata_dir)
    current_version = registry["current_version"]

    schema_key = f"v{current_version}"
    if schema_key not in registry["schemas"]:
        raise ValueError(f"Current version {current_version} not defined in schemas")

    return cast(dict[str, Any], registry["schemas"][schema_key])


def list_migrations(metadata_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    List all schema migrations from registry.

    Args:
        metadata_dir: Path to metadata directory (default: data/metadata)

    Returns:
        List of migration records sorted by version (ascending)

    Example:
        >>> migrations = list_migrations()
        >>> for m in migrations:
        ...     print(f"v{m['version']}: {m['title']} (Issue {m['issue']})")
        v2: CSV Metadata Optimization (Issue #59)
    """
    if metadata_dir is None:
        metadata_dir = _get_default_metadata_dir()

    registry = load_schema_registry(metadata_dir)

    migrations = registry.get("migrations", [])

    # Sort by version ascending
    migrations_sorted = sorted(migrations, key=lambda m: m["version"])

    return migrations_sorted


def get_column_definition(
    column_name: str, schema_version: int | None = None, metadata_dir: Path | None = None
) -> dict[str, Any] | None:
    """
    Get column definition from schema.

    Args:
        column_name: Name of column to lookup
        schema_version: Schema version (default: current version)
        metadata_dir: Path to metadata directory (default: data/metadata)

    Returns:
        Column definition dict or None if not found

    Example:
        >>> col = get_column_definition('row_hash')
        >>> print(f"Type: {col['type']}, Length: {col['length']}")
        Type: string, Length: 10
    """
    if metadata_dir is None:
        metadata_dir = _get_default_metadata_dir()

    registry = load_schema_registry(metadata_dir)

    if schema_version is None:
        schema_version = registry["current_version"]

    schema_key = f"v{schema_version}"
    if schema_key not in registry["schemas"]:
        raise ValueError(f"Schema version {schema_version} not found")

    schema_def = registry["schemas"][schema_key]
    columns = schema_def["partition_schema"]["columns"]

    for col in columns:
        if col["name"] == column_name:
            return cast(dict[str, Any], col)

    return None


__all__ = [
    "PartitionSchemaSummary",
    "SchemaCompatibilityState",
    "SchemaDetection",
    "clear_cache",
    "detect_schema_version",
    "get_column_definition",
    "get_compatible_read_versions",
    "get_current_schema",
    "get_schema_migration_guidance",
    "get_schema_version",
    "list_migrations",
    "load_schema_registry",
    "summarize_partition_schema_versions",
    "validate_column_names",
]
