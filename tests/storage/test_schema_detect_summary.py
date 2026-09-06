"""Identity tests for the schema_detect partition-summary split."""

from pathlib import Path

from finjuice.pipeline.storage import schema_detect, schema_detect_summary

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_summarize_lives_in_summary_module() -> None:
    """Partition summaries should not live in the detection module."""
    detect_text = (STORAGE_DIR / "schema_detect.py").read_text(encoding="utf-8")
    summary_text = (STORAGE_DIR / "schema_detect_summary.py").read_text(encoding="utf-8")

    assert "def detect_schema_version" in detect_text
    assert "def get_schema_version" in detect_text
    assert "class SchemaDetection" in detect_text
    assert "class PartitionSchemaSummary" in detect_text
    assert "def summarize_partition_schema_versions" not in detect_text
    assert "def summarize_partition_schema_versions" in summary_text
    assert "def detect_schema_version" not in summary_text
    assert "def get_schema_version" not in summary_text
    assert "class SchemaDetection" not in summary_text
    assert "class PartitionSchemaSummary" not in summary_text


def test_summarize_reexports_from_schema_detect() -> None:
    """Existing schema_detect imports should keep resolving to the summary."""
    assert (
        schema_detect.summarize_partition_schema_versions
        is schema_detect_summary.summarize_partition_schema_versions
    )
    assert callable(schema_detect.summarize_partition_schema_versions)
    assert callable(schema_detect.detect_schema_version)
    assert callable(schema_detect.get_schema_version)
    assert "summarize_partition_schema_versions" in schema_detect.__all__
    assert "detect_schema_version" in schema_detect.__all__
    assert "get_schema_version" in schema_detect.__all__
    assert "PartitionSchemaSummary" in schema_detect.__all__
