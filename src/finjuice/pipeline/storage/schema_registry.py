"""
Schema registry for CSV partition storage.

Provides programmatic access to schema definitions, migration history,
and column validation. Header matching and compatible-read detection live
in :mod:`finjuice.pipeline.storage.schema_detect` and are re-exported here
so existing callers can keep importing from this module.

Load/cache helpers live in
:mod:`finjuice.pipeline.storage.schema_registry_helpers` and are re-exported
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
    _header_matches_schema,
    _read_csv_header,
    detect_schema_version,
    get_compatible_read_versions,
    get_schema_version,
    summarize_partition_schema_versions,
)
from finjuice.pipeline.storage.schema_registry_helpers import (
    _get_default_metadata_dir,
    _load_registry_for_detection,
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


def get_schema_migration_guidance(
    detection: SchemaDetection | PartitionSchemaSummary,
    metadata_dir: Path | None = None,
) -> dict[str, str]:
    """Return actionable migration guidance for a detection result."""
    registry = _load_registry_for_detection(metadata_dir)
    current_version = int(registry["current_version"])
    compatibility = registry.get("compatibility", {}).get(f"v{current_version}", {})
    runtime_migration = str(
        compatibility.get(
            "runtime_migration",
            "Run finjuice refresh to rewrite readable legacy partitions to the active schema.",
        )
    )
    manual_migration = str(
        compatibility.get(
            "manual_migration",
            "scripts/migrate_schema_v3.py can be used for an explicit dry-run or eager rewrite.",
        )
    )

    if isinstance(detection, PartitionSchemaSummary):
        legacy_versions = detection.compatible_legacy_versions
        unsupported_versions = detection.unsupported_versions
        state = detection.state
    else:
        legacy_versions = (detection.version,) if detection.version is not None else ()
        unsupported_versions = (detection.version,)
        state = detection.state

    first_legacy_version = legacy_versions[0] if legacy_versions else None

    if state is SchemaCompatibilityState.COMPATIBLE_LEGACY and first_legacy_version is not None:
        return {
            "state": state.value,
            "command": "finjuice refresh",
            "message": (
                f"Detected compatible legacy schema v{first_legacy_version}. "
                f"Run finjuice refresh to rewrite partitions to v{current_version} and "
                "backfill category_rule/category_final."
            ),
            "detail": runtime_migration,
            "manual_check": manual_migration,
        }

    if state is SchemaCompatibilityState.UNSUPPORTED:
        version_labels = [
            f"v{version}" if version is not None else "unknown" for version in unsupported_versions
        ]
        version_label = ", ".join(version_labels) if version_labels else "unknown"
        schema_label = "schemas" if len(version_labels) > 1 else "schema"
        return {
            "state": state.value,
            "command": "finjuice doctor",
            "message": (
                f"Detected unsupported {schema_label} {version_label}; this finjuice build expects "
                f"v{current_version} or a compatible legacy version."
            ),
            "detail": (
                "Back up the data directory, run finjuice doctor, and migrate with an "
                "intermediate finjuice release if needed."
            ),
            "manual_check": manual_migration,
        }

    return {
        "state": SchemaCompatibilityState.ACTIVE.value,
        "command": "",
        "message": f"Partitions match active schema v{current_version}.",
        "detail": "",
        "manual_check": "",
    }


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


def validate_column_names(
    csv_path: Path, schema_version: int | None = None, metadata_dir: Path | None = None
) -> dict[str, Any]:
    """
    Validate CSV column names against schema.

    Args:
        csv_path: Path to CSV file to validate
        schema_version: Expected schema version (default: current)
        metadata_dir: Path to metadata directory (default: data/metadata)

    Returns:
        Validation result dict with keys:
        - valid: bool
        - errors: list[str] (empty if valid)
        - detected_version: int (auto-detected version)

    Example:
        >>> result = validate_column_names(Path('data/transactions/2025/07/transactions.csv'))
        >>> if result['valid']:
        ...     print(f"Valid v{result['detected_version']} schema")
        ... else:
        ...     for error in result['errors']:
        ...         print(f"Error: {error}")
    """
    if not csv_path.exists():
        return {"valid": False, "errors": [f"File not found: {csv_path}"], "detected_version": None}

    try:
        header = list(_read_csv_header(csv_path))
        detection = detect_schema_version(csv_path, metadata_dir)
    except ValueError as e:
        return {"valid": False, "errors": [str(e)], "detected_version": None}

    if not detection.is_supported or detection.version is None:
        return {
            "valid": False,
            "errors": [
                (
                    f"Could not detect schema version for {csv_path}. "
                    f"Header has {len(detection.header)} columns: {list(detection.header[:3])}..."
                )
            ],
            "detected_version": detection.version,
            "compatibility_state": detection.state.value,
        }

    detected_version = detection.version

    # If specific version requested, check match
    if schema_version is not None and detected_version != schema_version:
        return {
            "valid": False,
            "errors": [f"Expected schema v{schema_version}, detected v{detected_version}"],
            "detected_version": detected_version,
            "compatibility_state": detection.state.value,
        }

    # Load expected columns
    registry = _load_registry_for_detection(metadata_dir)
    schema_key = f"v{detected_version}"
    schema_def = registry["schemas"][schema_key]
    expected_columns = [col["name"] for col in schema_def["partition_schema"]["columns"]]

    # Validate column names
    errors = []
    if not _header_matches_schema(tuple(header), schema_def):
        if len(header) != len(expected_columns):
            errors.append(
                f"Column count mismatch: expected {len(expected_columns)}, got {len(header)}"
            )

        for i, (actual, expected) in enumerate(zip(header, expected_columns)):
            if actual != expected:
                errors.append(f"Column {i}: expected '{expected}', got '{actual}'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "detected_version": detected_version,
        "compatibility_state": detection.state.value,
    }


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
