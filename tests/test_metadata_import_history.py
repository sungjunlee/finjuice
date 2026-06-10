"""
Tests for import history tracking.

Tests file_id generation, import recording, archiving, and metadata CRUD operations.
"""

import re
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.metadata.import_history import (
    archive_source_file,
    generate_file_id,
    get_metadata_path,
    get_source_file_info,
    list_source_files,
    record_import,
)


class TestGenerateFileId:
    """Test file_id generation logic."""

    def test_generate_file_id_from_banksalad_filename(self):
        """Should extract date from Banksalad XLSX filename format."""
        # Arrange
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        existing_ids = set()

        # Act
        file_id = generate_file_id(file_path, existing_ids)

        # Assert
        assert file_id == "241027_1"
        assert len(file_id) == 8

    def test_generate_file_id_increments_for_same_day(self):
        """Should auto-increment suffix for multiple files on same day."""
        # Arrange
        file_path_2 = Path("data/imports/2024-10-27~2024-11-27.xlsx")
        existing_ids = {"241027_1"}  # First file already registered

        # Act
        file_id = generate_file_id(file_path_2, existing_ids)

        # Assert
        assert file_id == "241027_2"

    def test_generate_file_id_handles_triple_digits(self):
        """Should handle >99 files on same day (unlikely but possible)."""
        # Arrange
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        existing_ids = {f"241027_{i}" for i in range(1, 100)}

        # Act
        file_id = generate_file_id(file_path, existing_ids)

        # Assert
        assert file_id == "241027_100"
        assert len(file_id) == 10  # Acceptable length increase for edge case

    def test_generate_file_id_fallback_for_non_standard_filename(self):
        """Should use short hash fallback for non-standard filenames."""
        # Arrange
        file_path = Path("data/imports/banksalad_export.xlsx")
        existing_ids = set()

        # Act
        file_id = generate_file_id(file_path, existing_ids)

        # Assert
        # Fallback: 8-char hex hash
        assert len(file_id) == 8
        assert re.match(r"^[0-9a-f]{8}$", file_id)

    def test_generate_file_id_format_validation(self):
        """Generated file_id should match expected format."""
        # Arrange
        file_path = Path("data/imports/2025-03-15~2025-04-15.xlsx")
        existing_ids = set()

        # Act
        file_id = generate_file_id(file_path, existing_ids)

        # Assert
        # Format: YYMMDD_N
        assert re.match(r"^\d{6}_\d+$", file_id)


class TestArchiveSourceFile:
    """Test source file archiving."""

    def test_archive_source_file_creates_copy(self, tmp_path):
        """Should copy source file to archive directory."""
        # Arrange
        source_file = tmp_path / "source.xlsx"
        source_file.write_text("test data")
        archive_dir = tmp_path / "archives"
        file_id = "241027_1"

        # Act
        archived_path = archive_source_file(source_file, archive_dir, file_id)

        # Assert
        assert archived_path.exists()
        assert archived_path == archive_dir / f"{file_id}.xlsx"
        assert archived_path.read_text() == "test data"

    def test_archive_source_file_creates_archive_dir(self, tmp_path):
        """Should auto-create archive directory if it doesn't exist."""
        # Arrange
        source_file = tmp_path / "source.xlsx"
        source_file.write_text("test data")
        archive_dir = tmp_path / "archives"
        assert not archive_dir.exists()

        # Act
        archived_path = archive_source_file(source_file, archive_dir, "241027_1")

        # Assert
        assert archive_dir.exists()
        assert archived_path.exists()

    def test_archive_source_file_missing_source_raises_error(self, tmp_path):
        """Should raise FileNotFoundError if source file doesn't exist."""
        # Arrange
        source_file = tmp_path / "nonexistent.xlsx"
        archive_dir = tmp_path / "archives"

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            archive_source_file(source_file, archive_dir, "241027_1")


class TestRecordImport:
    """Test import recording."""

    def test_record_import_without_archive(self, tmp_path):
        """Should record new import without archiving."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        file_mtime = "2025-11-01T16:05:51.207892"
        source_rows = 597

        # Act
        file_id = record_import(metadata_dir, file_path, file_mtime, source_rows, archived=False)

        # Assert
        assert file_id == "241027_1"

        # Verify metadata file created
        metadata_file = metadata_dir / "import_history.csv"
        assert metadata_file.exists()

        # Verify content (new 7-column schema)
        df = pl.read_csv(metadata_file)
        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["file_id"] == "241027_1"
        assert row["original_filename"] == "2024-10-27~2025-10-27.xlsx"
        assert row["imported_from"] == str(file_path)
        assert row["archived"] == "no"
        # Empty string may be read as empty string or None by polars
        assert row["archived_path"] is None or row["archived_path"] == ""
        assert str(row["source_rows"]) == "597"  # May be read as int
        assert "imported_at" in row

    def test_record_import_with_archive(self, tmp_path):
        """Should record import with archive flag and path."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        file_mtime = "2025-11-01T16:05:51"
        source_rows = 597
        archived_path = Path("data/metadata/archives/241027_1.xlsx")

        # Act
        record_import(
            metadata_dir,
            file_path,
            file_mtime,
            source_rows,
            archived=True,
            archived_path=archived_path,
        )

        # Assert
        df = pl.read_csv(metadata_dir / "import_history.csv")
        row = df.row(0, named=True)
        assert row["archived"] == "yes"
        assert row["archived_path"] == str(archived_path)

    def test_record_import_preserves_paths_as_private_local_metadata(self, tmp_path):
        """Import history intentionally keeps raw local path metadata for auditability."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        archived_path = Path("data/metadata/archives/241027_1.xlsx")

        # Act
        record_import(
            metadata_dir,
            file_path,
            "2025-11-01T16:05:51",
            597,
            archived=True,
            archived_path=archived_path,
        )

        # Assert
        row = pl.read_csv(metadata_dir / "import_history.csv").row(0, named=True)
        assert row["original_filename"] == file_path.name
        assert row["imported_from"] == str(file_path)
        assert row["archived_path"] == str(archived_path)

    def test_record_import_duplicate_returns_existing_id(self, tmp_path):
        """Should return existing file_id for already-registered file."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        file_mtime = "2025-11-01T16:05:51"
        source_rows = 597

        # Act - record twice
        file_id_1 = record_import(metadata_dir, file_path, file_mtime, source_rows)
        file_id_2 = record_import(metadata_dir, file_path, file_mtime, source_rows)

        # Assert - same file_id returned
        assert file_id_1 == file_id_2

        # Verify only one entry in metadata
        df = pl.read_csv(metadata_dir / "import_history.csv")
        assert len(df) == 1

    def test_record_import_multiple_files(self, tmp_path):
        """Should handle multiple import recordings."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        imports = [
            (Path("data/imports/2024-10-27~2025-10-27.xlsx"), "2025-11-01T16:05:51", 597),
            (Path("data/imports/2024-11-27~2025-11-27.xlsx"), "2025-11-02T10:20:30", 423),
            (Path("data/imports/2024-10-27~2024-12-27.xlsx"), "2025-11-03T14:30:45", 801),
        ]

        # Act
        file_ids = [record_import(metadata_dir, path, mtime, rows) for path, mtime, rows in imports]

        # Assert
        assert file_ids == ["241027_1", "241127_1", "241027_2"]

        # Verify all entries in metadata
        df = pl.read_csv(metadata_dir / "import_history.csv")
        assert len(df) == 3
        # source_rows may be read as int or str by polars
        assert [str(x) for x in df["source_rows"].to_list()] == ["597", "423", "801"]

    def test_record_import_creates_metadata_directory(self, tmp_path):
        """Should auto-create metadata directory if it doesn't exist."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        assert not metadata_dir.exists()

        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        file_mtime = "2025-11-01T16:05:51"

        # Act
        record_import(metadata_dir, file_path, file_mtime, 597)

        # Assert
        assert metadata_dir.exists()
        assert (metadata_dir / "import_history.csv").exists()


class TestGetSourceFileInfo:
    """Test import history lookup."""

    def test_get_source_file_info_success(self, tmp_path):
        """Should retrieve import info by file_id."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        file_path = Path("data/imports/2024-10-27~2025-10-27.xlsx")
        file_mtime = "2025-11-01T16:05:51"
        file_id = record_import(metadata_dir, file_path, file_mtime, 597)

        # Act
        info = get_source_file_info(metadata_dir, file_id)

        # Assert
        assert info is not None
        assert info["file_id"] == "241027_1"
        assert info["original_filename"] == "2024-10-27~2025-10-27.xlsx"
        assert info["imported_from"] == str(file_path)
        assert info["source_rows"] == 597  # Polars returns int, not string

    def test_get_source_file_info_not_found(self, tmp_path):
        """Should return None for non-existent file_id."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir(parents=True)

        # Act
        info = get_source_file_info(metadata_dir, "999999_1")

        # Assert
        assert info is None

    def test_get_source_file_info_empty_metadata(self, tmp_path):
        """Should return None when metadata file doesn't exist."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir(parents=True)

        # Act
        info = get_source_file_info(metadata_dir, "241027_1")

        # Assert
        assert info is None


class TestListSourceFiles:
    """Test listing all import history."""

    def test_list_source_files_empty(self, tmp_path):
        """Should return empty DataFrame when no imports recorded."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir(parents=True)

        # Act
        df = list_source_files(metadata_dir)

        # Assert
        assert len(df) == 0
        # Verify new 7-column schema
        assert df.columns == [
            "file_id",
            "original_filename",
            "imported_from",
            "archived",
            "archived_path",
            "imported_at",
            "source_rows",
        ]

    def test_list_source_files_multiple_entries(self, tmp_path):
        """Should list all import history records."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        imports = [
            (Path("data/imports/2024-10-27~2025-10-27.xlsx"), "2025-11-01T16:05:51", 597),
            (Path("data/imports/2024-11-27~2025-11-27.xlsx"), "2025-11-02T10:20:30", 423),
        ]

        for path, mtime, rows in imports:
            record_import(metadata_dir, path, mtime, rows)

        # Act
        df = list_source_files(metadata_dir)

        # Assert
        assert len(df) == 2
        assert df["file_id"].to_list() == ["241027_1", "241127_1"]
        assert df["archived"].to_list() == ["no", "no"]


class TestGetMetadataPath:
    """Test metadata path construction."""

    def test_get_metadata_path(self, tmp_path):
        """Should construct correct metadata file path."""
        # Arrange
        metadata_dir = tmp_path / "metadata"

        # Act
        path = get_metadata_path(metadata_dir)

        # Assert
        assert path == metadata_dir / "import_history.csv"
        assert isinstance(path, Path)
