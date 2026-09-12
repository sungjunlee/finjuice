"""Tests for import-history skip helpers used by ingest/doctor."""

from pathlib import Path

from finjuice.pipeline.metadata.import_history_helpers import (
    list_unprocessed_xlsx,
    processed_original_filenames,
)


def _write_history(metadata_dir: Path, filenames: list[str]) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "file_id,original_filename,imported_from,archived,archived_path,imported_at,source_rows"
    ]
    for index, name in enumerate(filenames, start=1):
        lines.append(f"250101_{index},{name},/tmp/{name},no,,2025-01-01T00:00:00,1")
    (metadata_dir / "import_history.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_processed_original_filenames_empty_without_history(tmp_path: Path) -> None:
    assert processed_original_filenames(tmp_path / "metadata") == frozenset()


def test_list_unprocessed_xlsx_skips_history_basenames(tmp_path: Path) -> None:
    imports_dir = tmp_path / "imports"
    metadata_dir = tmp_path / "metadata"
    imports_dir.mkdir()
    (imports_dir / "done.xlsx").write_bytes(b"placeholder")
    (imports_dir / "new.xlsx").write_bytes(b"placeholder")
    _write_history(metadata_dir, ["done.xlsx"])

    unprocessed = list_unprocessed_xlsx(imports_dir, metadata_dir)

    assert [path.name for path in unprocessed] == ["new.xlsx"]
    assert processed_original_filenames(metadata_dir) == frozenset({"done.xlsx"})
