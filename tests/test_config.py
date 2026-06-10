"""
Tests for Configuration and Path Management.

Tests config loading, environment variable handling, default path resolution,
the unified default directory, and directory creation.
"""

import threading
from pathlib import Path

import pytest

from finjuice.pipeline.config import (
    Config,
    _ensure_directory,
    get_default_data_dir,
    is_inside_program_repo,
)


class TestConfigFromEnv:
    """Test Config.from_env() with various precedence scenarios."""

    def test_from_env_with_explicit_path(self, monkeypatch, tmp_path):
        """Test that explicit data_dir argument takes highest precedence."""
        # Arrange - Set env var but provide explicit path
        monkeypatch.setenv("FINJUICE_DATA_DIR", "/should/be/ignored")
        explicit_path = tmp_path / "explicit"

        # Act
        config = Config.from_env(data_dir=explicit_path)

        # Assert - Explicit path wins
        assert config.data_dir == explicit_path.resolve()

    def test_from_env_with_environment_variable(self, monkeypatch, tmp_path):
        """Test that FINJUICE_DATA_DIR environment variable is used."""
        # Arrange - Set env var, no explicit path
        env_path = tmp_path / "from_env"
        monkeypatch.setenv("FINJUICE_DATA_DIR", str(env_path))

        # Act
        config = Config.from_env()

        # Assert - Environment variable is used
        assert config.data_dir == env_path.resolve()

    def test_from_env_with_default_path(self, monkeypatch, tmp_path):
        """Test unified default path when no config or ENV override exists."""
        # Arrange - Clear environment variables and isolate home/config state
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr("finjuice.pipeline.config.load_config", lambda: None)

        # Act
        config = Config.from_env()

        # Assert - Uses unified ~/.finjuice default
        expected = tmp_path / ".finjuice"
        assert config.data_dir == expected

    def test_from_env_with_tilde_expansion(self, monkeypatch):
        """Test that tilde (~) is expanded correctly in paths."""
        # Arrange - Use tilde in env var
        monkeypatch.setenv("FINJUICE_DATA_DIR", "~/custom/finance")

        # Act
        config = Config.from_env()

        # Assert - Tilde is expanded
        assert config.data_dir == (Path.home() / "custom" / "finance")
        assert "~" not in str(config.data_dir)

    def test_from_env_with_string_argument(self, tmp_path):
        """Test that data_dir can be provided as string."""
        # Arrange
        path_str = str(tmp_path / "string_path")

        # Act
        config = Config.from_env(data_dir=path_str)

        # Assert - String is converted to Path
        assert isinstance(config.data_dir, Path)
        assert config.data_dir == Path(path_str).resolve()


class TestConfigPathProperties:
    """Test Config path properties return correct subdirectories."""

    def test_import_dir_property(self, tmp_path):
        """Test import_dir returns correct path."""
        # Arrange
        config = Config(data_dir=tmp_path)

        # Act
        import_dir = config.import_dir

        # Assert
        assert import_dir == tmp_path / "imports"
        assert isinstance(import_dir, Path)

    def test_export_dir_property(self, tmp_path):
        """Test export_dir returns correct path."""
        # Arrange
        config = Config(data_dir=tmp_path)

        # Act
        export_dir = config.export_dir

        # Assert
        assert export_dir == tmp_path / "exports"
        assert isinstance(export_dir, Path)

    def test_reports_dir_property(self, tmp_path):
        """Test reports_dir returns correct nested path."""
        # Arrange
        config = Config(data_dir=tmp_path)

        # Act
        reports_dir = config.reports_dir

        # Assert
        assert reports_dir == tmp_path / "exports" / "reports"
        assert isinstance(reports_dir, Path)

    def test_rules_file_property(self, tmp_path):
        """Test rules_file returns correct file path."""
        # Arrange
        config = Config(data_dir=tmp_path)

        # Act
        rules_file = config.rules_file

        # Assert
        assert rules_file == tmp_path / "rules.yaml"
        assert isinstance(rules_file, Path)

    def test_csv_base_dir_property(self, tmp_path):
        """Test csv_base_dir returns correct path for CSV partitions."""
        # Arrange
        config = Config(data_dir=tmp_path)

        # Act
        csv_base_dir = config.csv_base_dir

        # Assert
        assert csv_base_dir == tmp_path / "transactions"
        assert isinstance(csv_base_dir, Path)


class TestConfigEnsureDirs:
    """Test Config.ensure_dirs() directory creation."""

    def test_ensure_dirs_creates_all_directories(self, tmp_path):
        """Test that ensure_dirs creates all required directories."""
        # Arrange
        data_dir = tmp_path / "finance"
        config = Config(data_dir=data_dir)

        # Act
        config.ensure_dirs()

        # Assert - All directories exist
        assert config.data_dir.exists()
        assert config.data_dir.is_dir()
        assert config.import_dir.exists()
        assert config.import_dir.is_dir()
        assert config.export_dir.exists()
        assert config.export_dir.is_dir()
        assert config.reports_dir.exists()
        assert config.reports_dir.is_dir()
        assert config.csv_base_dir.exists()
        assert config.csv_base_dir.is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path):
        """Test that ensure_dirs can be called multiple times safely."""
        # Arrange
        config = Config(data_dir=tmp_path / "finance")
        config.ensure_dirs()

        # Act - Call again
        config.ensure_dirs()

        # Assert - No errors, directories still exist
        assert config.data_dir.exists()
        assert config.import_dir.exists()

    def test_ensure_dirs_does_not_create_rules_file(self, tmp_path):
        """Test that ensure_dirs does NOT create rules.yaml file."""
        # Arrange
        config = Config(data_dir=tmp_path / "finance")

        # Act
        config.ensure_dirs()

        # Assert - Rules file should NOT exist
        assert not config.rules_file.exists()

    def test_ensure_dirs_with_nested_path(self, tmp_path):
        """Test that ensure_dirs creates nested parent directories."""
        # Arrange - Deep nested path that doesn't exist
        deep_path = tmp_path / "level1" / "level2" / "level3" / "finance"
        config = Config(data_dir=deep_path)

        # Act
        config.ensure_dirs()

        # Assert - All nested directories created
        assert deep_path.exists()
        assert config.import_dir.exists()


class TestConfigValidation:
    """Test Config.validate() path validation."""

    def test_validate_with_valid_directory(self, tmp_path):
        """Test validation passes for valid directory."""
        # Arrange
        data_dir = tmp_path / "finance"
        data_dir.mkdir()
        config = Config(data_dir=data_dir)

        # Act & Assert - Should not raise
        config.validate()

    def test_validate_with_nonexistent_directory(self, tmp_path):
        """Test validation passes when directory doesn't exist yet."""
        # Arrange
        data_dir = tmp_path / "finance"
        config = Config(data_dir=data_dir)

        # Act & Assert - Should not raise (directory will be created later)
        config.validate()

    def test_validate_fails_when_path_is_file(self, tmp_path):
        """Test validation fails when data_dir is a file, not a directory."""
        # Arrange
        data_file = tmp_path / "not_a_directory.txt"
        data_file.touch()
        config = Config(data_dir=data_file)

        # Act & Assert - Should raise ValueError
        import pytest

        with pytest.raises(ValueError, match="is a file, not a directory"):
            config.validate()

    def test_validate_fails_when_parent_missing_absolute_path(self, tmp_path):
        """Test validation fails when parent directory doesn't exist (absolute paths)."""
        # Arrange
        data_dir = tmp_path / "nonexistent_parent" / "finance"
        config = Config(data_dir=data_dir)

        # Act & Assert - Should raise FileNotFoundError
        import pytest

        with pytest.raises(FileNotFoundError, match="Parent directory does not exist"):
            config.validate()

    def test_validate_with_relative_path(self, tmp_path, monkeypatch):
        """Test validation works with relative paths."""
        # Arrange
        monkeypatch.chdir(tmp_path)
        config = Config(data_dir=Path("./finance"))

        # Act & Assert - Should not raise
        config.validate()

    def test_validate_rejects_data_dir_inside_program_repo(self, tmp_path, monkeypatch):
        """Test validation rejects private data under the program repository."""
        # Arrange
        repo_root = tmp_path / "finjuice"
        repo_root.mkdir()
        data_dir = repo_root / "data"
        monkeypatch.setattr("finjuice.pipeline.config._get_program_repo_root", lambda: repo_root)
        config = Config(data_dir=data_dir)

        # Act & Assert
        with pytest.raises(ValueError, match="program repository"):
            config.validate()

    def test_ensure_dirs_rejects_data_dir_inside_program_repo(self, tmp_path, monkeypatch):
        """Test directory creation refuses to create private data under the repo."""
        # Arrange
        repo_root = tmp_path / "finjuice"
        repo_root.mkdir()
        data_dir = repo_root / "data"
        monkeypatch.setattr("finjuice.pipeline.config._get_program_repo_root", lambda: repo_root)
        config = Config(data_dir=data_dir)

        # Act & Assert
        with pytest.raises(ValueError, match="Financial data must live outside"):
            config.ensure_dirs()
        assert not data_dir.exists()

    def test_is_inside_program_repo_returns_false_without_source_checkout(
        self, tmp_path, monkeypatch
    ):
        """Test installed package contexts without a git checkout do not block normal paths."""
        monkeypatch.setattr("finjuice.pipeline.config._get_program_repo_root", lambda: None)

        assert not is_inside_program_repo(tmp_path / "finance")


class TestConfigIntegration:
    """Integration tests for Config class."""

    def test_full_workflow_with_file_operations(self, tmp_path):
        """Test complete workflow: create config, ensure dirs, verify structure."""
        # Arrange
        data_dir = tmp_path / "finance_data"
        config = Config.from_env(data_dir=data_dir)

        # Act - Validate and create directories
        config.validate()
        config.ensure_dirs()

        # Assert - Can create files in directories
        test_file = config.import_dir / "test.xlsx"
        test_file.touch()
        assert test_file.exists()

        test_report = config.reports_dir / "report.csv"
        test_report.touch()
        assert test_report.exists()

    def test_config_with_relative_path(self, tmp_path, monkeypatch):
        """Test that relative paths are resolved to absolute."""
        # Arrange - Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Act
        config = Config.from_env(data_dir="./relative/path")

        # Assert - Path is absolute
        assert config.data_dir.is_absolute()
        assert "relative" in str(config.data_dir)

    def test_config_equality(self, tmp_path):
        """Test that Config instances with same data_dir are equal."""
        # Arrange
        config1 = Config(data_dir=tmp_path)
        config2 = Config(data_dir=tmp_path)

        # Act & Assert - Dataclass equality
        assert config1 == config2
        assert config1.data_dir == config2.data_dir


class TestGetDefaultDataDir:
    """Test get_default_data_dir() function for the unified default."""

    def test_returns_finjuice_home_path(self, monkeypatch, tmp_path):
        """Test that ~/.finjuice is always returned."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = get_default_data_dir()

        assert result == tmp_path / ".finjuice"

    def test_returns_finjuice_home_when_data_exists_but_no_transactions(
        self, monkeypatch, tmp_path
    ):
        """Test ~/.finjuice path when ./data exists but no transactions subdir."""
        # Arrange - Create ./data but without transactions
        legacy_data = tmp_path / "data"
        legacy_data.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        result = get_default_data_dir()

        # Assert - Returns ~/.finjuice path (legacy not fully set up)
        expected = tmp_path / ".finjuice"
        assert result == expected

    def test_path_is_identical_across_platforms(self, monkeypatch, tmp_path):
        """Test that the default path no longer changes by platform."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        result = get_default_data_dir()

        # Assert
        assert result == tmp_path / ".finjuice"
        assert result.name == ".finjuice"

    def test_returns_path_object(self, monkeypatch, tmp_path):
        """Test that get_default_data_dir returns a Path object."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        result = get_default_data_dir()

        # Assert
        assert isinstance(result, Path)


class TestEnsureDirectoryTOCTOU:
    """Test _ensure_directory() TOCTOU race condition protection (Issue #57)."""

    def test_concurrent_directory_creation_with_10_threads(self, tmp_path):
        """Test TOCTOU protection with 10 concurrent threads creating same directory."""
        # Arrange
        test_dir = tmp_path / "concurrent_test"
        results = []
        errors = []

        def create_dir():
            """Thread worker: attempt to create directory."""
            try:
                result = _ensure_directory(test_dir, "test directory")
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Act - Spawn 10 threads to create same directory simultaneously
        threads = [threading.Thread(target=create_dir) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert - All threads should succeed without errors
        assert len(errors) == 0, f"Unexpected errors in concurrent creation: {errors}"
        assert len(results) == 10, "All 10 threads should return successfully"
        assert test_dir.is_dir(), "Directory should exist after concurrent creation"

        # Assert - All results point to same directory
        for result in results:
            assert result == test_dir

    def test_directory_to_file_race_condition_detected(self, tmp_path):
        """Test TOCTOU detection when directory is replaced with file (attack scenario)."""
        # Arrange - Create directory first
        test_path = tmp_path / "race_victim"
        test_path.mkdir(parents=True)

        # Simulate attacker: replace directory with file (race condition)
        test_path.rmdir()
        test_path.touch()

        # Act & Assert - Should detect that path is not a directory
        with pytest.raises(ValueError) as exc_info:
            _ensure_directory(test_path, "test directory")

        # Assert - Error message mentions TOCTOU or "not a directory"
        error_msg = str(exc_info.value)
        assert "not a directory" in error_msg.lower() or "toctou" in error_msg.lower()

    def test_successful_directory_creation(self, tmp_path):
        """Test normal directory creation works correctly."""
        # Arrange
        test_dir = tmp_path / "normal_creation"

        # Act
        result = _ensure_directory(test_dir, "test directory")

        # Assert
        assert result == test_dir
        assert test_dir.is_dir()

    def test_existing_directory_returns_successfully(self, tmp_path):
        """Test that existing directory is returned without error."""
        # Arrange - Create directory first
        test_dir = tmp_path / "existing"
        test_dir.mkdir(parents=True)

        # Act
        result = _ensure_directory(test_dir, "test directory")

        # Assert
        assert result == test_dir
        assert test_dir.is_dir()

    def test_nested_directory_creation(self, tmp_path):
        """Test creating nested directories (parents=True behavior)."""
        # Arrange
        deep_dir = tmp_path / "level1" / "level2" / "level3"

        # Act
        result = _ensure_directory(deep_dir, "nested directory")

        # Assert
        assert result == deep_dir
        assert deep_dir.is_dir()
        assert (tmp_path / "level1").is_dir()
        assert (tmp_path / "level1" / "level2").is_dir()

    def test_permission_error_propagates_with_context(self, tmp_path):
        """Test that PermissionError includes helpful context."""
        # Arrange - Create directory and make parent read-only
        parent_dir = tmp_path / "readonly_parent"
        parent_dir.mkdir()
        test_dir = parent_dir / "subdir"

        # Make parent read-only (no write permission)
        parent_dir.chmod(0o444)

        try:
            # Act & Assert
            with pytest.raises(PermissionError) as exc_info:
                _ensure_directory(test_dir, "test directory")

            # Assert - Error message includes context
            error_msg = str(exc_info.value)
            assert "test directory" in error_msg
            assert str(test_dir) in error_msg

        finally:
            # Cleanup - Restore permissions
            parent_dir.chmod(0o755)

    def test_context_parameter_in_error_messages(self, tmp_path):
        """Test that context parameter appears in error messages."""
        # Arrange - Create file instead of directory
        test_path = tmp_path / "file_not_dir"
        test_path.touch()

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            _ensure_directory(test_path, "custom context name")

        # Assert - Error message includes custom context
        error_msg = str(exc_info.value)
        assert "custom context name" in error_msg or str(test_path) in error_msg

    def test_symlink_attack_detected(self, tmp_path):
        """Test that symlink attacks are detected and rejected.

        Security Test: Verifies that _ensure_directory() rejects symlinks,
        preventing attackers from creating symlinks to sensitive files
        (e.g., /etc/passwd) that could be overwritten.
        """
        # Arrange - Create a symlink to a directory (simulating attack)
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        symlink_path = tmp_path / "malicious_symlink"
        symlink_path.symlink_to(target_dir)

        # Act & Assert - Should reject symlink even if it points to a directory
        with pytest.raises(ValueError) as exc_info:
            _ensure_directory(symlink_path, "test directory")

        # Assert - Error message indicates symlink detection
        error_msg = str(exc_info.value)
        assert "symlink" in error_msg.lower() or "toctou" in error_msg.lower()

    @pytest.mark.parametrize(
        "platform_name,expected_keywords",
        [
            ("Darwin", ["ls -la", "chmod u+w", "~/.finjuice"]),
            ("Linux", ["ls -la", "chmod u+w", "~/.finjuice"]),
            ("Windows", ["Properties", "Security", "%USERPROFILE%\\.finjuice"]),
        ],
    )
    def test_permission_error_platform_specific(
        self, tmp_path, monkeypatch, platform_name, expected_keywords
    ):
        """Test platform-specific permission error messages."""
        monkeypatch.setattr("platform.system", lambda: platform_name)

        # Create read-only parent directory
        readonly_parent = tmp_path / "readonly"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o444)

        # Try to create subdirectory (should fail with PermissionError)
        with pytest.raises(PermissionError) as exc_info:
            _ensure_directory(readonly_parent / "subdir", "test directory")

        error_msg = str(exc_info.value)

        # Verify emoji formatting
        assert "❌" in error_msg
        assert "💡" in error_msg
        assert "🔧" in error_msg

        # Verify 3-part structure
        assert "Cannot create" in error_msg
        assert "Permission denied" in error_msg
        assert "finjuice init --help" in error_msg

        # Verify platform-specific keywords
        for keyword in expected_keywords:
            assert keyword in error_msg, f"Missing keyword '{keyword}' for {platform_name}"

    def test_disk_full_error_message(self, tmp_path, monkeypatch):
        """Test disk space error message."""

        # Mock OSError with disk full message
        def mock_mkdir(*args, **kwargs):
            raise OSError("[Errno 28] No space left on device")

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        # Mock disk_usage to return low free space
        from collections import namedtuple

        DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
        monkeypatch.setattr(
            "shutil.disk_usage",
            lambda p: DiskUsage(total=100 * 1024**3, used=99 * 1024**3, free=1 * 1024**3),
        )

        with pytest.raises(OSError) as exc_info:
            _ensure_directory(tmp_path / "test", "test directory")

        error_msg = str(exc_info.value)

        # Verify emoji formatting
        assert "❌" in error_msg
        assert "💡" in error_msg
        assert "📊" in error_msg
        assert "🔧" in error_msg

        # Verify disk space info
        assert "No disk space" in error_msg
        assert "GB" in error_msg  # Free space in GB

        # Verify suggestions
        assert "Free up disk space" in error_msg
        assert "finjuice init --data-dir" in error_msg
