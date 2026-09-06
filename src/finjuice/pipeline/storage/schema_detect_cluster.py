"""Runtime-registry and compatible-read helpers for schema detection.

Owns packaged/local registry loading for header identification and the
compatible-read version window used by detection. The public detection API
stays in :mod:`finjuice.pipeline.storage.schema_detect`, which re-exports
these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import yaml


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
