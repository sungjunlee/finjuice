"""Identity tests for the index_collections helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import index_collections, index_collections_helpers

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_index_counting_helpers_live_in_helper_module() -> None:
    """Filesystem counting helpers should not live in the collection catalog module."""
    collections_text = (COMMANDS_DIR / "index_collections.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "index_collections_helpers.py").read_text(encoding="utf-8")

    assert "def _transactions_collection" in collections_text
    assert "def _rules_collection" in collections_text
    assert "def _collection_entry" in collections_text
    assert "COLLECTION_SPECS" in collections_text
    assert "def _iso_mtime" not in collections_text
    assert "def _latest_mtime" not in collections_text
    assert "def _safe_yaml_count" not in collections_text
    assert "def _yaml_signal_count" not in collections_text
    assert "def _csv_row_count" not in collections_text
    assert "def _iso_mtime" in helpers_text
    assert "def _latest_mtime" in helpers_text
    assert "def _safe_yaml_count" in helpers_text
    assert "def _yaml_signal_count" in helpers_text
    assert "def _csv_row_count" in helpers_text


def test_index_counting_helpers_reexport_from_index_collections() -> None:
    """Existing index_collections imports should keep resolving to the counting helpers."""
    collections_text = (COMMANDS_DIR / "index_collections.py").read_text(encoding="utf-8")

    assert "def _transactions_collection" in collections_text
    assert "_iso_mtime" in collections_text
    assert "_latest_mtime" in collections_text
    assert "_safe_yaml_count" in collections_text
    assert "_yaml_signal_count" in collections_text
    assert "_csv_row_count" in collections_text
    assert index_collections._iso_mtime is index_collections_helpers._iso_mtime
    assert index_collections._latest_mtime is index_collections_helpers._latest_mtime
    assert index_collections._safe_yaml_count is index_collections_helpers._safe_yaml_count
    assert index_collections._yaml_signal_count is index_collections_helpers._yaml_signal_count
    assert index_collections._csv_row_count is index_collections_helpers._csv_row_count
    assert callable(index_collections._transactions_collection)
    assert callable(index_collections._rules_collection)
    assert callable(index_collections._collection_entry)
