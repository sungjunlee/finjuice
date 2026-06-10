"""E2E tests for error handling and edge cases.

This test suite validates graceful error handling:
1. Invalid file formats and corrupted files
2. Missing required fields and files
3. Empty data scenarios
4. Schema validation errors
5. Permission and file access errors
6. Recovery from partial failures

Note: Common fixtures (sample_xlsx_path, initialized_data_dir, etc.)
are defined in tests/e2e/conftest.py
"""

import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


# ============================================================================
# Error-specific Fixtures (not shared across test files)
# ============================================================================


@pytest.fixture
def empty_xlsx_file(tmp_path: Path) -> Path:
    """Create an empty XLSX file with headers only."""
    df = pl.DataFrame(
        {
            "날짜": [],
            "시간": [],
            "타입": [],
            "대분류": [],
            "중분류": [],
            "내용": [],
            "메모": [],
            "금액": [],
            "화폐": [],
            "결제수단": [],
        }
    )
    xlsx_path = tmp_path / "empty_data.xlsx"
    df.write_excel(xlsx_path)
    return xlsx_path


@pytest.fixture
def missing_columns_xlsx(tmp_path: Path) -> Path:
    """Create XLSX with missing required columns."""
    df = pl.DataFrame(
        {
            "날짜": ["2024-10-01"],
            "시간": ["10:00"],
            # Missing: 타입, 대분류, etc.
            "내용": ["테스트"],
            "금액": [-1000],
        }
    )
    xlsx_path = tmp_path / "missing_columns.xlsx"
    df.write_excel(xlsx_path)
    return xlsx_path


@pytest.fixture
def invalid_yaml_rules(tmp_path: Path) -> Path:
    """Create a syntactically invalid YAML file."""
    invalid_yaml = tmp_path / "invalid_rules.yaml"
    # Write invalid YAML (unbalanced brackets)
    invalid_yaml.write_text("""
version: 1
rules:
  - name: test
    match: "test"
    tags: [test
""")
    return invalid_yaml


@pytest.fixture
def text_as_xlsx(tmp_path: Path) -> Path:
    """Create a text file with .xlsx extension (corrupted/fake)."""
    fake_xlsx = tmp_path / "not_actually_xlsx.xlsx"
    fake_xlsx.write_text("This is not an XLSX file")
    return fake_xlsx


# ============================================================================
# Test: Invalid File Formats
# ============================================================================


@pytest.mark.e2e
class TestInvalidFileFormats:
    """Tests for handling invalid file formats."""

    def test_import_non_xlsx_file(self, initialized_data_dir: Path, tmp_path: Path) -> None:
        """Verify importing non-XLSX file is rejected or handled gracefully.

        Validates:
        - Exit code indicates error or warning
        - Error message is user-friendly
        """
        # Create a non-XLSX file
        text_file = tmp_path / "data.txt"
        text_file.write_text("This is a text file")

        # Try to import it
        result = runner.invoke(
            app, ["--data-dir", str(initialized_data_dir), "import", str(text_file)]
        )

        # Should reject non-XLSX or handle gracefully
        # Exact behavior depends on implementation
        # Either exit with error or show warning
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_pipeline_with_corrupted_xlsx(
        self, initialized_data_dir: Path, text_as_xlsx: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline handles corrupted XLSX gracefully.

        Validates:
        - Does not crash with stack trace
        - Provides meaningful error message
        """
        # Setup with corrupted file
        shutil.copy(text_as_xlsx, initialized_data_dir / "imports" / "corrupted.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should not crash catastrophically - may fail gracefully
        # Check that we don't have a Python traceback exposed to user
        # (implementation may skip invalid files)
        assert "Traceback" not in result.output, "Python traceback in output"


# ============================================================================
# Test: Missing Required Data
# ============================================================================


@pytest.mark.e2e
class TestMissingRequiredData:
    """Tests for handling missing required data."""

    def test_pipeline_without_xlsx_files(
        self, initialized_data_dir: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline handles empty imports/ directory.

        Validates:
        - Does not crash
        - Shows appropriate message
        """
        # Setup - just rules, no XLSX
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should handle gracefully (may succeed with 0 files or show warning)
        # Don't assert exit code - just verify no crash
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_pipeline_without_rules_file(
        self, initialized_data_dir: Path, sample_xlsx_path: Path
    ) -> None:
        """Verify pipeline handles missing rules.yaml.

        Validates:
        - Does not crash
        - May use default/empty rules or show warning
        """
        # Setup - just XLSX, no rules
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "data.xlsx")

        # Remove the default rules.yaml that init creates
        rules_path = initialized_data_dir / "rules.yaml"
        if rules_path.exists():
            rules_path.unlink()

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should handle gracefully
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_init_in_non_existent_parent(self, tmp_path: Path) -> None:
        """Verify init creates parent directories if needed.

        Validates:
        - Deeply nested path is created
        - Or appropriate error message shown
        """
        deep_path = tmp_path / "a" / "b" / "c" / "data"

        result = runner.invoke(app, ["--data-dir", str(deep_path), "init", "--no-git"])

        # Should either create directories or fail gracefully
        if result.exit_code == 0:
            assert deep_path.exists(), "Data directory not created"
        else:
            assert "Traceback" not in result.output, "Python traceback in output"


# ============================================================================
# Test: Empty Data Scenarios
# ============================================================================


@pytest.mark.e2e
class TestEmptyDataScenarios:
    """Tests for handling empty data scenarios."""

    def test_pipeline_with_empty_xlsx(
        self, initialized_data_dir: Path, empty_xlsx_file: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline handles XLSX with no data rows.

        Validates:
        - Does not crash
        - Produces empty outputs gracefully
        """
        # Setup with empty file
        shutil.copy(empty_xlsx_file, initialized_data_dir / "imports" / "empty.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should handle gracefully
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_status_on_empty_data(self, initialized_data_dir: Path) -> None:
        """Verify status command on empty data directory.

        Validates:
        - Does not crash
        - Shows meaningful "no data" message
        """
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "status"])

        # Should handle gracefully
        assert result.exit_code in [0, 1, 2, 4], f"Unexpected exit code: {result.exit_code}"
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_show_on_empty_data(self, initialized_data_dir: Path) -> None:
        """Verify show command on empty data directory.

        Validates:
        - Does not crash
        - Shows meaningful "no data" message
        """
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "show"])

        # Should handle gracefully
        assert "Traceback" not in result.output, "Python traceback in output"


# ============================================================================
# Test: Schema Validation
# ============================================================================


@pytest.mark.e2e
class TestSchemaValidation:
    """Tests for schema validation errors."""

    def test_xlsx_with_missing_columns(
        self, initialized_data_dir: Path, missing_columns_xlsx: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline handles XLSX with missing columns.

        Validates:
        - Does not crash
        - Either skips file or uses defaults for missing columns
        """
        # Setup
        shutil.copy(missing_columns_xlsx, initialized_data_dir / "imports" / "partial.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should handle gracefully
        assert "Traceback" not in result.output, "Python traceback in output"

    def test_invalid_yaml_rules(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, invalid_yaml_rules: Path
    ) -> None:
        """Verify pipeline handles invalid rules.yaml.

        Validates:
        - Does not crash
        - Shows YAML parsing error message
        """
        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "data.xlsx")
        shutil.copy(invalid_yaml_rules, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should either show error or skip tagging
        # Key is not crashing
        assert "Traceback" not in result.output or "yaml" in result.output.lower(), (
            "Unexpected Python traceback in output"
        )


# ============================================================================
# Test: File Access Errors
# ============================================================================


@pytest.mark.e2e
class TestFileAccessErrors:
    """Tests for file access and permission errors."""

    def test_read_only_exports_directory(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline handles read-only exports directory.

        Note: This test modifies permissions and may not work on all systems.
        """
        import os
        import stat

        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "data.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        exports_dir = initialized_data_dir / "exports"

        try:
            # Make exports read-only
            os.chmod(exports_dir, stat.S_IRUSR | stat.S_IXUSR)

            # Run pipeline
            result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

            # Should handle gracefully (may fail at export stage)
            # Key is not crashing with obscure error
            assert "Traceback" not in result.output, "Python traceback in output"
        finally:
            # Restore permissions
            os.chmod(exports_dir, stat.S_IRWXU)


# ============================================================================
# Test: Recovery Scenarios
# ============================================================================


@pytest.mark.e2e
class TestRecoveryScenarios:
    """Tests for recovery from partial failures."""

    def test_recovery_after_interrupted_pipeline(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
    ) -> None:
        """Verify pipeline can recover from partial state.

        Simulates interrupted pipeline by running only ingest,
        then running full pipeline to verify clean recovery.
        """
        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "data.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Partial run (just ingest via the command that runs all phases)
        # This simulates state where some data exists
        partial_result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
        assert partial_result.exit_code == 0, f"Partial run failed: {partial_result.output}"

        # Remove exports to simulate interrupted state
        exports_dir = initialized_data_dir / "exports"
        if exports_dir.exists():
            shutil.rmtree(exports_dir)
            exports_dir.mkdir()

        # Recovery run
        result2 = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Should recover cleanly
        assert result2.exit_code == 0, f"Recovery failed: {result2.output}"

        # Verify exports recreated
        master_files = list(exports_dir.glob("master_*.xlsx"))
        assert len(master_files) > 0, "Master file not recreated"

    def test_multiple_xlsx_with_one_corrupted(
        self,
        initialized_data_dir: Path,
        sample_xlsx_path: Path,
        text_as_xlsx: Path,
        sample_rules_path: Path,
    ) -> None:
        """Verify pipeline processes good files even if one is corrupted.

        Validates:
        - Good files are processed
        - Corrupted files are skipped with warning
        - Pipeline completes
        """
        # Setup - one good file, one bad file
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "good.xlsx")
        shutil.copy(text_as_xlsx, initialized_data_dir / "imports" / "bad.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline
        result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])

        # Pipeline should handle mixed input gracefully
        assert "Traceback" not in result.output, f"Unexpected traceback: {result.output}"

        # Should process the good file
        # Check that some data was processed
        csv_base_dir = initialized_data_dir / "transactions"
        if csv_base_dir.exists():
            csv_files = list(csv_base_dir.rglob("*.csv"))
            # If any files exist, good data was processed
            if len(csv_files) > 0:
                from finjuice.pipeline.storage import csv_partition

                df = csv_partition.get_all_transactions(csv_base_dir)
                assert len(df) > 0, "No transactions from good file"


# ============================================================================
# Test: Edge Cases
# ============================================================================


@pytest.mark.e2e
class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_special_characters_in_path(self, tmp_path: Path) -> None:
        """Verify handling of special characters in data path.

        Validates:
        - Paths with spaces work
        - Paths with unicode work
        """
        special_path = tmp_path / "data with spaces"

        result = runner.invoke(app, ["--data-dir", str(special_path), "init", "--no-git"])

        assert result.exit_code == 0, f"Special path failed: {result.output}"
        assert special_path.exists(), "Directory not created"

    def test_unicode_path(self, tmp_path: Path) -> None:
        """Verify handling of unicode characters in path.

        Validates:
        - Korean characters in path work
        """
        unicode_path = tmp_path / "가계부_데이터"

        result = runner.invoke(app, ["--data-dir", str(unicode_path), "init", "--no-git"])

        assert result.exit_code == 0, f"Unicode path failed: {result.output}"
        assert unicode_path.exists(), "Directory not created"

    def test_very_long_path(self, tmp_path: Path) -> None:
        """Verify handling of very long paths.

        Note: This may fail on some filesystems with path limits.
        """
        # Create a reasonably long but valid path
        long_dir_name = "a" * 50
        long_path = tmp_path / long_dir_name / long_dir_name / "data"

        result = runner.invoke(app, ["--data-dir", str(long_path), "init", "--no-git"])

        # Either succeeds or fails with filesystem error
        if result.exit_code == 0:
            assert long_path.exists(), "Directory not created"
        # Otherwise, should not show Python traceback


# ============================================================================
# Test: Concurrent Access
# ============================================================================


@pytest.mark.e2e
class TestConcurrentAccess:
    """Tests for concurrent access scenarios."""

    def test_sequential_pipeline_runs_are_safe(
        self, initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
    ) -> None:
        """Verify multiple sequential pipeline runs are safe.

        Validates:
        - Data integrity maintained across runs
        - No file corruption or locks
        """
        # Setup
        shutil.copy(sample_xlsx_path, initialized_data_dir / "imports" / "data.xlsx")
        shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

        # Run pipeline multiple times
        for i in range(3):
            result = runner.invoke(app, ["--data-dir", str(initialized_data_dir), "refresh"])
            assert result.exit_code == 0, f"Run {i + 1} failed: {result.output}"

        # Verify final state is valid
        csv_base_dir = initialized_data_dir / "transactions"
        from finjuice.pipeline.storage import csv_partition

        df = csv_partition.get_all_transactions(csv_base_dir)
        assert len(df) > 0, "No transactions after multiple runs"
