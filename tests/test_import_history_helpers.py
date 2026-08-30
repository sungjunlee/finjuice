"""Identity tests for the import_history helper split."""

from pathlib import Path

from finjuice.pipeline.metadata import import_history, import_history_helpers

METADATA_DIR = Path("src/finjuice/pipeline/metadata")


def test_lookup_helpers_live_in_helper_module() -> None:
    """History CSV path and lookup helpers should not live in the write-path module."""
    history_text = (METADATA_DIR / "import_history.py").read_text(encoding="utf-8")
    helpers_text = (METADATA_DIR / "import_history_helpers.py").read_text(encoding="utf-8")

    assert "def record_import" in history_text
    assert "def generate_file_id" in history_text
    assert "def archive_source_file" in history_text
    assert "def get_metadata_path" not in history_text
    assert "def get_source_file_info" not in history_text
    assert "def list_source_files" not in history_text
    assert "def get_metadata_path" in helpers_text
    assert "def get_source_file_info" in helpers_text
    assert "def list_source_files" in helpers_text


def test_lookup_helpers_reexport_from_import_history() -> None:
    """Existing import_history imports should keep resolving to the lookup helpers."""
    assert import_history.get_metadata_path is import_history_helpers.get_metadata_path
    assert import_history.get_source_file_info is import_history_helpers.get_source_file_info
    assert import_history.list_source_files is import_history_helpers.list_source_files
    assert callable(import_history.record_import)
    assert callable(import_history.generate_file_id)
    assert callable(import_history.archive_source_file)
