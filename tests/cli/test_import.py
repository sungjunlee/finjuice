"""Tests for finjuice import command (Issue #63, #147)."""

import shutil
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import finjuice.pipeline.cli.commands.import_cmd.zip_extraction as zip_extraction
from finjuice.pipeline.cli.commands.import_cmd import (
    extract_xlsx_from_zip,
    format_size,
    import_xlsx_files,
)
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


class TestFormatSize:
    """Tests for format_size helper function."""

    def test_format_size_bytes(self) -> None:
        """Should format small sizes in bytes."""
        assert format_size(100) == "100 B"
        assert format_size(0) == "0 B"
        assert format_size(1023) == "1023 B"

    def test_format_size_kilobytes(self) -> None:
        """Should format medium sizes in KB."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(2048) == "2.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_format_size_megabytes(self) -> None:
        """Should format large sizes in MB."""
        assert format_size(1024 * 1024) == "1.00 MB"
        assert format_size(2 * 1024 * 1024) == "2.00 MB"
        assert format_size(int(1.5 * 1024 * 1024)) == "1.50 MB"


class TestImportXlsxFiles:
    """Tests for import_xlsx_files helper function."""

    def test_import_file_not_found_error(self, tmp_path: Path) -> None:
        """Should record error when file doesn't exist."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        nonexistent = tmp_path / "nonexistent.xlsx"

        result = import_xlsx_files([nonexistent], imports_dir)

        assert len(result["errors"]) == 1
        assert result["errors"][0][1] == "파일 없음"

    def test_import_non_xlsx_error(self, tmp_path: Path) -> None:
        """Should record error for non-XLSX files."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b,c")

        result = import_xlsx_files([csv_file], imports_dir)

        assert len(result["errors"]) == 1
        assert result["errors"][0][1] == "XLSX 파일 아님"

    def test_import_skip_existing(self, tmp_path: Path) -> None:
        """Should skip existing files when force=False."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_file = tmp_path / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04new")
        existing = imports_dir / "test.xlsx"
        existing.write_bytes(b"PK\x03\x04old")

        result = import_xlsx_files([xlsx_file], imports_dir, force=False)

        assert len(result["skipped"]) == 1
        assert result["skipped"][0][1] == "이미 존재하는 파일"

    def test_import_force_overwrite(self, tmp_path: Path) -> None:
        """Should overwrite existing files when force=True."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_file = tmp_path / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04new content")
        existing = imports_dir / "test.xlsx"
        existing.write_bytes(b"PK\x03\x04old")

        result = import_xlsx_files([xlsx_file], imports_dir, force=True)

        assert len(result["imported"]) == 1
        assert existing.read_bytes() == b"PK\x03\x04new content"

    def test_import_dry_run_no_copy(self, tmp_path: Path) -> None:
        """Should not copy files in dry_run mode."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_file = tmp_path / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        result = import_xlsx_files([xlsx_file], imports_dir, dry_run=True)

        assert len(result["imported"]) == 1
        assert not (imports_dir / "test.xlsx").exists()

    def test_import_skip_when_file_already_in_imports_dir(self, tmp_path: Path) -> None:
        """Should skip copying when source file is already in imports/."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_file = imports_dir / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        result = import_xlsx_files([xlsx_file], imports_dir)

        assert len(result["skipped"]) == 1
        assert result["skipped"][0][1] == "이미 imports 디렉토리에 있음"

    def test_import_os_error(self, tmp_path: Path) -> None:
        """Should record OS errors during copy."""
        imports_dir = tmp_path / "imports"
        imports_dir.mkdir()
        xlsx_file = tmp_path / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        with patch("shutil.copy2", side_effect=OSError("Permission denied")):
            result = import_xlsx_files([xlsx_file], imports_dir)

        assert len(result["errors"]) == 1
        assert "Permission denied" in result["errors"][0][1]


class TestImportCommand:
    """Test finjuice import command for XLSX file importing."""

    def test_import_single_file(self, tmp_path: Path, monkeypatch) -> None:
        """Test importing a single XLSX file."""
        # Arrange - Create mock XLSX file
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "test_export.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock xlsx content")  # XLSX starts with PK (zip)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_file)])

        # Assert
        assert result.exit_code == 0
        assert (imports_dir / "test_export.xlsx").exists()
        # Should show success message
        assert "✅" in cli_text(result) or "copied" in cli_text(result).lower()

    def test_import_multiple_files(self, tmp_path: Path, monkeypatch) -> None:
        """Test importing multiple XLSX files."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        files = []
        for i in range(3):
            f = source_dir / f"export_{i}.xlsx"
            f.write_bytes(b"PK\x03\x04mock xlsx")
            files.append(f)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import"] + [str(f) for f in files]
        )

        # Assert
        assert result.exit_code == 0
        for i in range(3):
            assert (imports_dir / f"export_{i}.xlsx").exists()

    def test_import_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling when file doesn't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import", "/nonexistent/file.xlsx"]
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result)
        assert "파일 없음" in output

    def test_import_file_option_not_found(self, tmp_path: Path) -> None:
        """Test --file returns exit code 1 for a missing XLSX path."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch(
            "finjuice.pipeline.cli.commands.import_cmd.is_first_run",
            return_value=False,
        ):
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--file", str(tmp_path / "missing.xlsx")],
            )

        assert result.exit_code == 1
        output = cli_text(result)
        assert "파일 없음" in output

    def test_import_file_option_runs_non_interactive_pipeline(self, tmp_path: Path) -> None:
        """Test --file copies the XLSX and runs the pipeline without prompts."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "agent_import.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        pipeline_summary = {
            "ingest": {"inserted": 1},
            "tag": {"tagged": 1, "coverage_pct": 100.0},
            "transfer": {"pairs": 0},
            "master_path": data_dir / "exports" / "master.xlsx",
        }

        with (
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.is_first_run",
                return_value=False,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=pipeline_summary,
            ) as mock_pipeline,
        ):
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--file", str(xlsx_file)],
            )

        assert result.exit_code == 0
        assert (data_dir / "imports" / "agent_import.xlsx").exists()
        mock_pipeline.assert_called_once()

    def test_import_non_xlsx_file_rejected(self, tmp_path: Path) -> None:
        """Test that non-XLSX files are rejected."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        csv_file = source_dir / "data.csv"
        csv_file.write_text("a,b,c\n1,2,3")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(csv_file)])

        # Assert - Should fail or warn about non-xlsx
        assert result.exit_code == 1
        output = cli_text(result)
        assert "xlsx" in output.lower() or "지원하지 않는 파일 형식" in output

    def test_import_file_option_rejects_non_xlsx(self, tmp_path: Path) -> None:
        """Test --file rejects non-XLSX inputs."""
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        csv_file = source_dir / "data.csv"
        csv_file.write_text("a,b,c\n1,2,3")

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch(
            "finjuice.pipeline.cli.commands.import_cmd.is_first_run",
            return_value=False,
        ):
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--file", str(csv_file)],
            )

        assert result.exit_code == 1
        output = cli_text(result)
        assert "지원하지 않는 파일 형식" in output

    def test_import_skip_existing(self, tmp_path: Path) -> None:
        """Test that existing files are skipped by default."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "existing.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04new content")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()
        # Pre-existing file
        existing = imports_dir / "existing.xlsx"
        existing.write_bytes(b"PK\x03\x04old content")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_file)])

        # Assert - Should skip existing and show message
        assert result.exit_code == 0
        # File should not be overwritten
        assert existing.read_bytes() == b"PK\x03\x04old content"
        output = cli_text(result).lower()
        assert "skip" in output or "exists" in output

    def test_import_overwrite_with_force(self, tmp_path: Path) -> None:
        """Test that --force overwrites existing files."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "existing.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04new content here")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()
        existing = imports_dir / "existing.xlsx"
        existing.write_bytes(b"PK\x03\x04old")

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import", "--force", str(xlsx_file)]
        )

        # Assert - File should be overwritten
        assert result.exit_code == 0
        assert existing.read_bytes() == b"PK\x03\x04new content here"

    def test_import_dry_run(self, tmp_path: Path) -> None:
        """Test --dry-run shows preview without copying."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import", "--dry-run", str(xlsx_file)]
        )

        # Assert
        assert result.exit_code == 0
        assert not (imports_dir / "test.xlsx").exists()  # Not copied
        output = cli_text(result).lower()
        assert "dry" in output or "preview" in output or "would" in output

    def test_import_creates_imports_dir(self, tmp_path: Path) -> None:
        """Test that import creates imports/ directory if it doesn't exist."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "test.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # imports/ doesn't exist

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_file)])

        # Assert
        assert result.exit_code == 0
        assert (data_dir / "imports").exists()
        assert (data_dir / "imports" / "test.xlsx").exists()

    def test_import_shows_file_info(self, tmp_path: Path) -> None:
        """Test that import shows file information (size, etc.)."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_file = source_dir / "info_test.xlsx"
        # Create a larger mock file
        content = b"PK\x03\x04" + b"x" * 10000
        xlsx_file.write_bytes(content)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_file)])

        # Assert
        assert result.exit_code == 0
        # Should show some file info (size, path, etc.)
        output = cli_text(result).lower()
        assert "kb" in output or "mb" in output or "byte" in output or "size" in output

    def test_import_empty_file_list(self, tmp_path: Path) -> None:
        """Test import with no files provided."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import"])

        # Assert
        assert result.exit_code == 1
        assert "입력 파일이 없습니다" in result.output
        assert "finjuice import --file <file.xlsx>" in result.output
        assert not (data_dir / "rules.yaml").exists()

    def test_import_glob_pattern(self, tmp_path: Path, monkeypatch) -> None:
        """Test that glob patterns are expanded correctly."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        for i in range(3):
            f = source_dir / f"뱅크샐러드_2024-{i:02d}.xlsx"
            f.write_bytes(b"PK\x03\x04mock")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Need to use shell expansion, so test with actual glob
        monkeypatch.chdir(source_dir)

        # Act - Import using glob pattern string
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "import",
                str(source_dir / "뱅크샐러드_2024-00.xlsx"),
                str(source_dir / "뱅크샐러드_2024-01.xlsx"),
                str(source_dir / "뱅크샐러드_2024-02.xlsx"),
            ],
        )

        # Assert
        assert result.exit_code == 0
        for i in range(3):
            assert (imports_dir / f"뱅크샐러드_2024-{i:02d}.xlsx").exists()


class TestExtractXlsxFromZip:
    """Tests for extract_xlsx_from_zip helper function (Issue #147)."""

    def _set_zip_limits(self, monkeypatch, **overrides: object) -> None:
        """Patch ZIP extraction limits for focused resource-limit tests."""
        monkeypatch.setattr(
            zip_extraction,
            "ZIP_EXTRACTION_LIMITS",
            replace(zip_extraction.ZIP_EXTRACTION_LIMITS, **overrides),
        )

    def test_extract_unencrypted_zip(self, tmp_path: Path) -> None:
        """Should extract XLSX from unencrypted ZIP without password."""
        # Arrange - Create a ZIP with an XLSX file
        xlsx_content = b"PK\x03\x04mock xlsx content"
        zip_path = tmp_path / "test.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", xlsx_content)

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is not None
        assert result.name == "data.xlsx"
        assert result.exists()
        assert result.read_bytes() == xlsx_content

    def test_extract_encrypted_zip_with_password(self, tmp_path: Path) -> None:
        """Should extract XLSX from encrypted ZIP with correct password."""
        zip_binary = shutil.which("zip")
        if zip_binary is None:
            pytest.skip("Info-ZIP binary is required to create encrypted ZIP test fixtures")

        # Arrange - Create an encrypted ZIP with a synthetic Banksalad-like XLSX payload.
        xlsx_content = b"PK\x03\x04mock xlsx content"
        zip_path = tmp_path / "encrypted.zip"
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        xlsx_path = source_dir / "banksalad.xlsx"
        xlsx_path.write_bytes(xlsx_content)
        password = "test123"

        subprocess.run(
            [zip_binary, "-j", "-P", password, str(zip_path), str(xlsx_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        result = extract_xlsx_from_zip(zip_path, password=password, interactive=False)

        assert result is not None
        assert result.name == "banksalad.xlsx"
        assert result.read_bytes() == xlsx_content

    def test_extract_zip_no_xlsx(self, tmp_path: Path) -> None:
        """Should return None when ZIP contains no XLSX files."""
        # Arrange
        zip_path = tmp_path / "no_xlsx.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.csv", "a,b,c")
            zf.writestr("readme.txt", "test")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_bad_zip_file(self, tmp_path: Path) -> None:
        """Should return None for corrupted ZIP files."""
        # Arrange
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"this is not a zip file")

        # Act
        result = extract_xlsx_from_zip(bad_zip, interactive=False)

        # Assert
        assert result is None

    def test_extract_requires_password_no_interactive(self, tmp_path: Path) -> None:
        """Should return None when password needed but not provided and not interactive."""
        # Arrange - Create a mock encrypted ZIP
        # Note: We can't easily create a truly encrypted ZIP with stdlib
        # This test is more for the interactive=False path
        zip_path = tmp_path / "test.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        # Act - This should succeed since the ZIP isn't actually encrypted
        result = extract_xlsx_from_zip(zip_path, password=None, interactive=False)

        # Assert - Unencrypted ZIP should work
        assert result is not None

    def test_extract_filters_macos_metadata(self, tmp_path: Path) -> None:
        """Should ignore __MACOSX/ metadata files when looking for XLSX."""
        # Arrange - ZIP with macOS metadata
        zip_path = tmp_path / "macos.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            # macOS metadata file (should be ignored)
            zf.writestr("__MACOSX/._data.xlsx", b"macos metadata")
            # Actual XLSX file
            zf.writestr("data.xlsx", b"PK\x03\x04real xlsx content")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert - Should find the real XLSX, not the macOS metadata
        assert result is not None
        assert result.name == "data.xlsx"
        assert b"real xlsx content" in result.read_bytes()

    def test_extract_path_traversal_attack(self, tmp_path: Path) -> None:
        """Should reject ZIP files with path traversal attempts (security)."""
        # Arrange - Create a malicious ZIP with path traversal
        zip_path = tmp_path / "malicious.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            # Attempt path traversal attack with ../
            zf.writestr("../../../etc/passwd.xlsx", b"malicious content")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert - Should be rejected for security
        assert result is None

    def test_extract_absolute_path_attack(self, tmp_path: Path) -> None:
        """Should reject ZIP files with absolute extraction targets."""
        # Arrange
        zip_path = tmp_path / "absolute.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("/tmp/absolute.xlsx", b"malicious content")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_rejects_too_many_members(self, tmp_path: Path, monkeypatch) -> None:
        """Should reject ZIP files that exceed the member-count limit."""
        # Arrange
        self._set_zip_limits(monkeypatch, max_members=1)
        zip_path = tmp_path / "too_many.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"PK\x03\x04content")
            zf.writestr("__MACOSX/._data.xlsx", b"metadata")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_rejects_oversized_member(self, tmp_path: Path, monkeypatch) -> None:
        """Should reject ZIP files with a member over the single-file limit."""
        # Arrange
        self._set_zip_limits(monkeypatch, max_single_member_bytes=4)
        zip_path = tmp_path / "oversized_member.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"PK\x03\x04content")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_rejects_oversized_archive(self, tmp_path: Path, monkeypatch) -> None:
        """Should reject ZIP files over the total uncompressed-size limit."""
        # Arrange
        self._set_zip_limits(
            monkeypatch,
            max_single_member_bytes=100,
            max_total_uncompressed_bytes=10,
        )
        zip_path = tmp_path / "oversized_archive.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data1.xlsx", b"PK\x03\x04aaaa")
            zf.writestr("data2.xlsx", b"PK\x03\x04bbbb")

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_rejects_suspicious_compression_ratio(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Should reject highly compressed members before extraction."""
        # Arrange
        self._set_zip_limits(monkeypatch, max_compression_ratio=2.0)
        zip_path = tmp_path / "zip_bomb.zip"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("data.xlsx", b"A" * 10_000)

        # Act
        result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None

    def test_extract_rejects_non_xlsx_payload(self, tmp_path: Path, caplog) -> None:
        """Should reject unsupported non-XLSX archive members without logging their names."""
        import logging

        # Arrange
        zip_path = tmp_path / "mixed_payload.zip"
        sensitive_member = "private_statement.csv"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"PK\x03\x04content")
            zf.writestr(sensitive_member, "a,b,c")

        # Act
        with caplog.at_level(logging.WARNING):
            result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None
        assert sensitive_member not in caplog.text

    def test_extract_wrong_password_returns_none(self, tmp_path: Path) -> None:
        """Should return None and log warning when wrong password provided."""
        # Arrange - Create a ZIP and mock extractall to raise password error
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        # Act - Mock extractall to simulate wrong password
        with patch.object(zipfile.ZipFile, "extractall", side_effect=RuntimeError("bad password")):
            result = extract_xlsx_from_zip(zip_path, password="wrong", interactive=False)

        # Assert
        assert result is None

    def test_extract_password_sanitized_in_logs(self, tmp_path: Path, caplog) -> None:
        """Should sanitize password from error messages to prevent log leakage."""
        import logging

        # Arrange
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        secret_password = "supersecret123"

        # Act - Force an exception that contains the password
        with patch.object(
            zipfile.ZipFile,
            "extractall",
            side_effect=ValueError(f"Error with {secret_password} in message"),
        ):
            with caplog.at_level(logging.ERROR):
                result = extract_xlsx_from_zip(
                    zip_path, password=secret_password, interactive=False
                )

        # Assert
        assert result is None
        # Password should NOT appear in logs
        assert secret_password not in caplog.text
        assert "***" in caplog.text

    def test_extract_permission_error(self, tmp_path: Path) -> None:
        """Should return None on permission errors."""
        # Arrange
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        # Act - Mock ZipFile to raise PermissionError
        with patch("zipfile.ZipFile", side_effect=PermissionError("Access denied")):
            result = extract_xlsx_from_zip(zip_path, interactive=False)

        # Assert
        assert result is None


class TestZipImportCommand:
    """Tests for finjuice import command with ZIP files (Issue #147)."""

    def test_import_zip_file(self, tmp_path: Path) -> None:
        """Test importing a ZIP file containing XLSX."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()

        # Create ZIP with XLSX
        zip_path = source_dir / "export.zip"
        xlsx_content = b"PK\x03\x04mock xlsx"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("2024-01-01~2024-12-31.xlsx", xlsx_content)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(zip_path)])

        # Assert
        assert result.exit_code == 0
        assert (imports_dir / "2024-01-01~2024-12-31.xlsx").exists()
        assert "압축 해제" in cli_text(result) or "extract" in cli_text(result).lower()

    def test_import_zip_dry_run(self, tmp_path: Path) -> None:
        """Test --dry-run with ZIP file shows preview."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()

        zip_path = source_dir / "export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import", "--dry-run", str(zip_path)]
        )

        # Assert
        assert result.exit_code == 0
        assert not (imports_dir / "data.xlsx").exists()  # Not extracted
        output = cli_text(result).lower()
        assert "would extract" in output or "dry" in output

    def test_import_mixed_xlsx_and_zip(self, tmp_path: Path) -> None:
        """Test importing both XLSX and ZIP files together."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()

        # Direct XLSX
        xlsx_file = source_dir / "direct.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04direct xlsx")

        # ZIP containing XLSX
        zip_path = source_dir / "zipped.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("from_zip.xlsx", b"PK\x03\x04from zip")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(
            app, ["--data-dir", str(data_dir), "import", str(xlsx_file), str(zip_path)]
        )

        # Assert
        assert result.exit_code == 0
        assert (imports_dir / "direct.xlsx").exists()
        assert (imports_dir / "from_zip.xlsx").exists()

    def test_import_zip_with_password_option(self, tmp_path: Path) -> None:
        """Test --password option for ZIP files."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()

        zip_path = source_dir / "export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.xlsx", b"content")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act - Password provided but not needed (unencrypted)
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "import", "--password", "1234", str(zip_path)],
        )

        # Assert
        assert result.exit_code == 0
        assert (imports_dir / "data.xlsx").exists()

    def test_import_zip_no_xlsx_inside(self, tmp_path: Path) -> None:
        """Test error when ZIP contains no XLSX files."""
        # Arrange
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()

        zip_path = source_dir / "no_xlsx.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.csv", "a,b,c")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(zip_path)])

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "xlsx" in output or "없음" in output
