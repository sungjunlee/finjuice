"""Identity coverage for the schema_detect header-matching helper split."""

from __future__ import annotations

import importlib


def test_schema_detect_reexports_header_matching_helpers() -> None:
    """Header-matching helpers stay importable from schema_detect after the split."""
    detect = importlib.import_module("finjuice.pipeline.storage.schema_detect")
    helpers = importlib.import_module("finjuice.pipeline.storage.schema_detect_helpers")

    assert detect._read_csv_header is helpers._read_csv_header
    assert detect._schema_columns is helpers._schema_columns
    assert detect._header_matches_schema is helpers._header_matches_schema
    assert detect._missing_read_compatible_columns is helpers._missing_read_compatible_columns
    assert (
        detect._infer_read_compatible_legacy_version
        is helpers._infer_read_compatible_legacy_version
    )


def test_schema_detect_keeps_public_detection_api() -> None:
    """Public detection API names stay on schema_detect after the helper split."""
    detect = importlib.import_module("finjuice.pipeline.storage.schema_detect")

    assert detect.__all__ == [
        "PartitionSchemaSummary",
        "SchemaCompatibilityState",
        "SchemaDetection",
        "detect_schema_version",
        "get_compatible_read_versions",
        "get_schema_version",
        "summarize_partition_schema_versions",
    ]
    for name in detect.__all__:
        assert getattr(detect, name) is not None
