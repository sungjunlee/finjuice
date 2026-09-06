"""Structure tests for the schema_detect remaining helper-cluster split.

Runtime-registry loading and the compatible-read version window live in
``schema_detect_cluster`` and must stay identity-equal when re-exported from
``schema_detect``. Header matching stays in ``schema_detect_helpers``.
Partition summaries stay in ``schema_detect_summary``. Public detection
entry points stay in ``schema_detect``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

STORAGE_DIR = Path("src/finjuice/pipeline/storage")
CLUSTER_MODULE = "finjuice.pipeline.storage.schema_detect_cluster"
DETECT_MODULE = "finjuice.pipeline.storage.schema_detect"
HELPERS_MODULE = "finjuice.pipeline.storage.schema_detect_helpers"
SUMMARY_MODULE = "finjuice.pipeline.storage.schema_detect_summary"

PUBLIC_DETECT_NAMES = (
    "detect_schema_version",
    "get_schema_version",
)
CLUSTER_HELPER_NAMES = (
    "_load_runtime_registry",
    "_load_local_registry_for_header_matching",
    "_iter_schema_definitions_for_detection",
    "_version_number",
    "_compatible_read_versions",
    "get_compatible_read_versions",
)
HEADER_HELPER_NAMES = (
    "_read_csv_header",
    "_schema_columns",
    "_header_matches_schema",
    "_missing_read_compatible_columns",
    "_infer_read_compatible_legacy_version",
)


def test_schema_detect_reexports_cluster_identity() -> None:
    """Registry/compat helpers stay on schema_detect as re-exports after the split."""
    detect = importlib.import_module(DETECT_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(detect, name) is getattr(cluster, name)

    for name in PUBLIC_DETECT_NAMES:
        assert callable(getattr(detect, name))
    assert "get_compatible_read_versions" in detect.__all__
    assert "detect_schema_version" in detect.__all__
    assert "get_schema_version" in detect.__all__


def test_schema_detect_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in schema_detect_cluster."""
    detect = importlib.import_module(DETECT_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(detect, name).__module__ == CLUSTER_MODULE

    for name in PUBLIC_DETECT_NAMES:
        assert getattr(detect, name).__module__ == DETECT_MODULE


def test_cluster_lives_in_cluster_module() -> None:
    """Runtime-registry helpers should not live in the public detection module."""
    detect_text = (STORAGE_DIR / "schema_detect.py").read_text(encoding="utf-8")
    cluster_text = (STORAGE_DIR / "schema_detect_cluster.py").read_text(encoding="utf-8")
    helpers_text = (STORAGE_DIR / "schema_detect_helpers.py").read_text(encoding="utf-8")
    summary_text = (STORAGE_DIR / "schema_detect_summary.py").read_text(encoding="utf-8")

    for name in PUBLIC_DETECT_NAMES:
        assert f"def {name}" in detect_text
        assert f"def {name}" not in cluster_text

    assert "class SchemaDetection" in detect_text
    assert "class SchemaCompatibilityState" in detect_text
    assert "class PartitionSchemaSummary" in detect_text
    assert "class SchemaDetection" not in cluster_text
    assert "class SchemaCompatibilityState" not in cluster_text
    assert "class PartitionSchemaSummary" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in detect_text
        assert f"def {name}" in cluster_text
        assert name in detect_text
        assert f"def {name}" not in helpers_text
        assert f"def {name}" not in summary_text

    for name in HEADER_HELPER_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in detect_text

    assert "def summarize_partition_schema_versions" in summary_text
    assert "def summarize_partition_schema_versions" not in cluster_text
    assert "def summarize_partition_schema_versions" not in detect_text
