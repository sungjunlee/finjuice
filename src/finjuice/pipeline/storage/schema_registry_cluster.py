"""Compatibility helpers for the schema registry.

Owns migration guidance and CSV column-name validation against detected
schema versions. Public registry lookup APIs stay in
:mod:`finjuice.pipeline.storage.schema_registry`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.schema_detect import (
    PartitionSchemaSummary,
    SchemaCompatibilityState,
    SchemaDetection,
    _header_matches_schema,
    _read_csv_header,
    detect_schema_version,
)
from finjuice.pipeline.storage.schema_registry_helpers import _load_registry_for_detection


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
