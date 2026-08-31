"""Load and cache helpers for the schema registry.

Owns filesystem/packaged YAML loading, minimum-registry validation, and the
process-wide schema cache. Public registry query APIs stay in
:mod:`finjuice.pipeline.storage.schema_registry`, which re-exports this
public API so existing callers can keep importing from that module.
"""

from __future__ import annotations

import os
import threading
from importlib import resources
from pathlib import Path
from typing import Any, Final, cast

import yaml

# Thread-safe caching infrastructure
# Maps metadata_dir path (str) → schema dict
_schema_cache: dict[str, dict[str, Any]] = {}
_cache_lock: Final = threading.Lock()
_PACKAGED_SCHEMA_CACHE_KEY: Final = "__packaged_schema__"


def _get_default_metadata_dir() -> Path:
    """
    Get default metadata directory path.

    Uses environment variable BSALAD_DATA_DIR if set, otherwise defaults
    to OS-specific data directory (via get_default_data_dir).

    This ensures consistency with Config.from_env() defaults (Issue #82).

    Returns:
        Path to metadata directory
    """
    data_dir_env = os.environ.get("FINJUICE_DATA_DIR")
    if data_dir_env:
        return Path(data_dir_env) / "metadata"
    else:
        from finjuice.pipeline.config import get_default_data_dir

        return get_default_data_dir() / "metadata"


def _validate_schema_registry(schema: dict[str, Any]) -> None:
    """Validate the minimum schema registry structure used by callers."""
    if "current_version" not in schema:
        raise ValueError("Schema registry missing 'current_version' field")

    if "schemas" not in schema:
        raise ValueError("Schema registry missing 'schemas' field")


def _load_schema_file(schema_path: Path) -> dict[str, Any]:
    """Load and validate a schema registry from a filesystem path."""
    try:
        with open(schema_path, encoding="utf-8") as f:
            schema_raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse schema.yaml: {e}") from e

    schema = cast(dict[str, Any], schema_raw)
    _validate_schema_registry(schema)
    return schema


def _load_packaged_schema_registry() -> dict[str, Any]:
    """Load the packaged templates/schema.yaml registry for runtime diagnostics."""
    cached_schema = _schema_cache.get(_PACKAGED_SCHEMA_CACHE_KEY)
    if cached_schema is not None:
        return cached_schema

    with _cache_lock:
        cached_schema = _schema_cache.get(_PACKAGED_SCHEMA_CACHE_KEY)
        if cached_schema is not None:
            return cached_schema

        try:
            schema_resource = resources.files("finjuice.templates").joinpath("schema.yaml")
            with schema_resource.open("r", encoding="utf-8") as f:
                schema_raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Failed to parse packaged schema.yaml: {e}") from e

        schema = cast(dict[str, Any], schema_raw)
        _validate_schema_registry(schema)
        _schema_cache[_PACKAGED_SCHEMA_CACHE_KEY] = schema
        return schema


def _load_registry_for_detection(metadata_dir: Path | None) -> dict[str, Any]:
    """Load the packaged runtime registry used for compatibility decisions."""
    _ = metadata_dir
    return _load_packaged_schema_registry()


def load_schema_registry(metadata_dir: Path) -> dict[str, Any]:
    """
    Load schema.yaml from metadata directory.

    Thread Safety:
        Thread-safe via double-checked locking pattern with threading.Lock.
        Safe for use in multi-threaded environments (web servers, parallel tests).

        Implementation:
        - Fast path: Read-only cache check without lock (safe when cache hit)
        - Slow path: Acquire lock, double-check, load file if still uncached

    Caching:
        Schemas are cached in memory per metadata_dir path for performance.
        Multiple paths can be cached simultaneously.

        To manually clear cache after modifying schema.yaml:
            >>> clear_cache()

    Args:
        metadata_dir: Path to metadata directory containing schema.yaml

    Returns:
        Parsed schema dictionary

    Raises:
        FileNotFoundError: If schema.yaml doesn't exist
        ValueError: If schema.yaml is missing required fields
        yaml.YAMLError: If schema.yaml is malformed

    Example:
        >>> from pathlib import Path
        >>> schema = load_schema_registry(Path('data/metadata'))
        >>> print(f"Current version: {schema['current_version']}")
        Current version: 2
    """
    global _schema_cache

    cache_key = str(metadata_dir)

    # Fast path: cache hit without lock (read-only access is thread-safe)
    # Use .get() to avoid TOCTOU race with concurrent clear_cache()
    cached_schema = _schema_cache.get(cache_key)
    if cached_schema is not None:
        return cached_schema

    # Slow path: cache miss, acquire lock
    with _cache_lock:
        # Double-check: cache may have been initialized by another thread
        # while we were waiting for the lock
        cached_schema = _schema_cache.get(cache_key)
        if cached_schema is not None:
            return cached_schema

        # Cache miss - load from disk
        schema_path = metadata_dir / "schema.yaml"

        if not schema_path.exists():
            raise FileNotFoundError(
                f"Schema registry not found: {schema_path}. "
                f"Run 'finjuice schema init' to create it."
            )

        schema = _load_schema_file(schema_path)

        # Cache the schema (dictionary assignment is atomic in CPython)
        _schema_cache[cache_key] = schema

        return schema


def clear_cache() -> None:
    """
    Clear the schema registry cache.

    Call this after modifying schema.yaml or in test fixtures to force
    reload from disk. Clears all cached schemas for all paths.

    Thread Safety:
        Thread-safe. Acquires lock before clearing cache to prevent
        race conditions.

    Example:
        >>> clear_cache()
        >>> schema = load_schema_registry(Path('data/metadata'))  # Reloads from disk
    """
    global _schema_cache

    with _cache_lock:
        _schema_cache.clear()
