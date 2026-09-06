"""Structure tests for the schema_registry compatibility helper split.

Migration guidance and CSV column-name validation live in
``schema_registry_cluster`` and must stay identity-equal when re-exported
from ``schema_registry``, so existing import paths and monkeypatches keep
working after the split. Registry lookup stays in ``schema_registry``.
Load/cache helpers stay in ``schema_registry_helpers``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

STORAGE_DIR = Path("src/finjuice/pipeline/storage")
CLUSTER_MODULE = "finjuice.pipeline.storage.schema_registry_cluster"
REGISTRY_MODULE = "finjuice.pipeline.storage.schema_registry"
HELPERS_MODULE = "finjuice.pipeline.storage.schema_registry_helpers"

CLUSTER_NAMES = (
    "get_schema_migration_guidance",
    "validate_column_names",
)
LOOKUP_NAMES = (
    "get_current_schema",
    "list_migrations",
    "get_column_definition",
)
LOAD_CACHE_NAMES = (
    "load_schema_registry",
    "clear_cache",
)


def test_schema_registry_reexports_cluster_identity() -> None:
    """Compatibility helpers stay on schema_registry as re-exports after the split."""
    registry = importlib.import_module(REGISTRY_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_NAMES:
        assert getattr(registry, name) is getattr(cluster, name)

    for name in LOOKUP_NAMES + LOAD_CACHE_NAMES:
        assert callable(getattr(registry, name))


def test_schema_registry_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in schema_registry_cluster."""
    registry = importlib.import_module(REGISTRY_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(registry, name).__module__ == CLUSTER_MODULE

    for name in LOOKUP_NAMES:
        assert getattr(registry, name).__module__ == REGISTRY_MODULE


def test_compatibility_cluster_lives_in_cluster_module() -> None:
    """Guidance and column validation should not live in the registry lookup module."""
    registry_text = (STORAGE_DIR / "schema_registry.py").read_text(encoding="utf-8")
    cluster_text = (STORAGE_DIR / "schema_registry_cluster.py").read_text(encoding="utf-8")
    helpers_text = (STORAGE_DIR / "schema_registry_helpers.py").read_text(encoding="utf-8")

    for name in LOOKUP_NAMES:
        assert f"def {name}" in registry_text
        assert f"def {name}" not in cluster_text

    for name in CLUSTER_NAMES:
        assert f"def {name}" not in registry_text
        assert f"def {name}" in cluster_text
        assert name in registry_text

    for name in LOAD_CACHE_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in registry_text
