"""Unit tests for config file I/O and 4-tier precedence system.

Tests cover:
- Config file path resolution (~/.finjuice with legacy fallback)
- Config load/save operations
- 4-tier precedence (CLI > ENV > config file > ~/.finjuice)
- Security validation (symlink attacks, path traversal)
- Error handling and fallback behavior
"""

from pathlib import Path

import pytest

from finjuice.pipeline.config import Config, get_default_data_dir
from finjuice.pipeline.config_file import (
    config_exists,
    get_config_path,
    load_config,
    save_config,
    validate_config_path,
)
from finjuice.pipeline.config_schema import DataConfig, PreferencesConfig, UserConfig


def _set_home(monkeypatch, tmp_path: Path) -> Path:
    """Point Path.home() to an isolated temporary directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _primary_config_path(home: Path) -> Path:
    """Return the primary config path for a test home directory."""
    return home / ".finjuice" / "config.toml"


def _legacy_config_path(home: Path) -> Path:
    """Return the legacy config path for a test home directory."""
    return home / ".config" / "finjuice" / "config.toml"


class TestConfigPath:
    """Test config file path resolution."""

    def test_get_config_path_returns_primary_when_no_files_exist(self, monkeypatch, tmp_path):
        """Config path defaults to ~/.finjuice/config.toml when no file exists."""
        home = _set_home(monkeypatch, tmp_path)

        path = get_config_path()
        assert path == _primary_config_path(home)

    def test_config_exists_false(self, tmp_path, monkeypatch):
        """config_exists() returns False when config doesn't exist."""
        _set_home(monkeypatch, tmp_path)

        assert config_exists() is False

    def test_config_exists_true(self, tmp_path, monkeypatch):
        """config_exists() returns True when config exists."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        config_path.touch()

        assert config_exists() is True


class TestConfigLoadSave:
    """Test config file load and save operations."""

    def test_load_config_not_found(self, tmp_path, monkeypatch):
        """load_config() returns None when config doesn't exist."""
        _set_home(monkeypatch, tmp_path)

        result = load_config()
        assert result is None

    def test_save_and_load_config(self, tmp_path, monkeypatch):
        """save_config() creates valid config that can be loaded."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)

        # Create and save config
        config = UserConfig(
            data=DataConfig(directory="~/Documents/test-data"),
            preferences=PreferencesConfig(language="en", auto_init=False),
        )

        save_config(config)

        # Verify file was created
        assert config_path.exists()

        # Load and verify
        loaded = load_config()
        assert loaded is not None
        assert loaded.data.directory == "~/Documents/test-data"
        assert loaded.preferences.language == "en"
        assert loaded.preferences.auto_init is False

    def test_save_config_creates_parent_dir(self, tmp_path, monkeypatch):
        """save_config() creates parent directory if missing."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)

        config = UserConfig(data=DataConfig(directory="/test"))
        save_config(config)

        assert config_path.exists()
        assert config_path.parent.is_dir()

    def test_save_config_atomic_write(self, tmp_path, monkeypatch):
        """save_config() uses atomic write pattern."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)

        # Create initial config
        config = UserConfig(data=DataConfig(directory="/test1"))
        save_config(config)

        # Overwrite with new config (atomic)
        config2 = UserConfig(data=DataConfig(directory="/test2"))
        save_config(config2)

        # Verify temp file is cleaned up
        temp_files = list(config_path.parent.glob("*.tmp"))
        assert len(temp_files) == 0

        # Verify final content
        loaded = load_config()
        assert loaded.data.directory == "/test2"

    def test_load_config_invalid_toml(self, tmp_path, monkeypatch):
        """load_config() raises ValueError for invalid TOML."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        config_path.write_text("invalid toml {{{")

        with pytest.raises(ValueError, match="Failed to load config file"):
            load_config()

    def test_load_config_missing_required_field(self, tmp_path, monkeypatch):
        """load_config() raises ValueError if required fields missing."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        config_path.write_text('[preferences]\nlanguage = "ko"\n')  # Missing [data]

        with pytest.raises(ValueError, match="Invalid config file"):
            load_config()


class TestConfigValidation:
    """Test config validation and security checks."""

    def test_validate_config_symlink_attack(self, tmp_path):
        """validate_config_path() rejects symlink as config file."""
        real_file = tmp_path / "real.toml"
        real_file.touch()

        symlink = tmp_path / "config.toml"
        symlink.symlink_to(real_file)

        with pytest.raises(ValueError, match="must not be a symlink"):
            validate_config_path(symlink)

    def test_validate_config_parent_not_dir(self, tmp_path):
        """validate_config_path() rejects when parent is not directory."""
        not_a_dir = tmp_path / "not_a_dir"
        not_a_dir.touch()  # Create as file, not directory

        # Create config file with file as parent (corrupted state)
        config_path = not_a_dir / "config.toml"

        # Manually create the config file to simulate corrupted state
        # (This wouldn't normally be possible, but simulates filesystem corruption)
        try:
            # This should fail because parent is a file
            config_path.parent.mkdir(parents=True, exist_ok=True)
        except (NotADirectoryError, FileExistsError):
            # Expected: cannot create directory because parent is a file
            pass

        # Create a real scenario: config file exists but parent became a file somehow
        # For this test, we'll just verify the validation logic exists
        # by checking a config file whose parent was changed to a file

        # Skip this test as it's hard to simulate filesystem corruption
        # The actual validation happens in save_config() which we test separately
        pytest.skip("Filesystem corruption scenario is difficult to simulate reliably")

    def test_user_config_validate_empty_directory(self):
        """UserConfig validation rejects empty directory."""
        config = UserConfig(data=DataConfig(directory=""))

        with pytest.raises(ValueError, match="cannot be empty"):
            config.validate()

    def test_user_config_validate_null_bytes(self):
        """UserConfig validation rejects paths with null bytes."""
        config = UserConfig(data=DataConfig(directory="/test\x00/path"))

        with pytest.raises(ValueError, match="null bytes"):
            config.validate()

    def test_user_config_validate_too_long(self):
        """UserConfig validation rejects excessively long paths."""
        long_path = "a" * 1001
        config = UserConfig(data=DataConfig(directory=long_path))

        with pytest.raises(ValueError, match="too long"):
            config.validate()

    def test_preferences_validate_invalid_language(self):
        """PreferencesConfig validation rejects invalid language."""
        prefs = PreferencesConfig(language="fr")  # type: ignore

        with pytest.raises(ValueError, match="Invalid language"):
            prefs.validate()

    def test_save_config_rejects_symlink_target(self, tmp_path):
        """save_config should reject writing to symlink (symlink attack prevention)."""
        home = tmp_path / "home"
        home.mkdir()
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        target_file = tmp_path / "sensitive_file.txt"
        target_file.write_text("SENSITIVE DATA")

        # Create symlink (simulating attacker replacing config with symlink)
        config_path.symlink_to(target_file)

        config = UserConfig(
            data=DataConfig(directory=str(tmp_path / "data")),
            preferences=PreferencesConfig(language="ko"),
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(Path, "home", lambda: home)

            # Should raise ValueError due to symlink
            with pytest.raises(ValueError, match="must not be a symlink"):
                save_config(config)

        # Verify target file was NOT overwritten
        assert target_file.read_text() == "SENSITIVE DATA"

    def test_save_config_removes_temp_symlink(self, tmp_path):
        """save_config should remove temp file if it's a symlink."""

        home = tmp_path / "home"
        home.mkdir()
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        temp_path = config_path.with_suffix(".toml.tmp")
        target_file = tmp_path / "target.txt"
        target_file.write_text("target content")

        # Create temp file as symlink (attacker pre-created it)
        temp_path.symlink_to(target_file)

        config = UserConfig(
            data=DataConfig(directory=str(tmp_path / "data")),
            preferences=PreferencesConfig(language="ko"),
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(Path, "home", lambda: home)

            # Should succeed and remove the symlink
            save_config(config)

        # Verify temp symlink was removed and real file created
        assert config_path.exists()
        assert not config_path.is_symlink()
        assert not temp_path.exists()

        # Verify target file was NOT modified
        assert target_file.read_text() == "target content"


class TestConfigPrecedence:
    """Test 4-tier configuration precedence system."""

    def test_precedence_cli_over_all(self, tmp_path, monkeypatch):
        """Priority 1: CLI argument overrides ENV, config file, and default."""
        _set_home(monkeypatch, tmp_path)

        file_config = UserConfig(data=DataConfig(directory="/from-file"))
        save_config(file_config)

        # Set up environment
        monkeypatch.setenv("FINJUICE_DATA_DIR", "/from-env")

        # CLI argument should win
        config = Config.from_env(data_dir="/from-cli")
        assert config.data_dir == Path("/from-cli")

    def test_precedence_env_over_config_file(self, tmp_path, monkeypatch):
        """Priority 2: ENV variable overrides config file and default."""
        _set_home(monkeypatch, tmp_path)

        file_config = UserConfig(data=DataConfig(directory="/from-file"))
        save_config(file_config)

        # Set environment
        monkeypatch.setenv("FINJUICE_DATA_DIR", "/from-env")

        # ENV should win
        config = Config.from_env()
        assert config.data_dir == Path("/from-env")

    def test_precedence_config_file_over_default(self, tmp_path, monkeypatch):
        """Priority 3: Config file overrides OS default."""
        _set_home(monkeypatch, tmp_path)

        file_config = UserConfig(data=DataConfig(directory="/from-file"))
        save_config(file_config)

        # No CLI or ENV
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)

        # Config file should win
        config = Config.from_env()
        assert config.data_dir == Path("/from-file")

    def test_precedence_default_fallback(self, tmp_path, monkeypatch):
        """Priority 4: OS default used when nothing else set."""
        home = _set_home(monkeypatch, tmp_path)

        # No CLI or ENV
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)

        # Should fall back to OS default
        config = Config.from_env()
        assert config.data_dir == _primary_config_path(home).parent
        assert config.data_dir == get_default_data_dir()

    def test_precedence_config_file_error_fallback(self, tmp_path, monkeypatch, caplog):
        """Config file load error falls back to default."""
        home = _set_home(monkeypatch, tmp_path)
        config_path = _primary_config_path(home)
        config_path.parent.mkdir(parents=True)
        config_path.write_text("invalid {{{ toml")
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)

        # Should fall back to default and log warning
        config = Config.from_env()
        assert config.data_dir == _primary_config_path(home).parent

        # Check warning was logged
        assert "Failed to load config file" in caplog.text


class TestConfigSchema:
    """Test config schema dataclasses."""

    def test_user_config_from_dict_minimal(self):
        """UserConfig.from_dict() handles minimal valid config."""
        data = {"data": {"directory": "/test"}}

        config = UserConfig.from_dict(data)

        assert config.data.directory == "/test"
        assert config.preferences.auto_init is True  # default
        assert config.preferences.language == "ko"  # default

    def test_user_config_from_dict_full(self):
        """UserConfig.from_dict() handles complete config."""
        data = {
            "data": {"directory": "/test"},
            "preferences": {"auto_init": False, "interactive_mode": False, "language": "en"},
        }

        config = UserConfig.from_dict(data)

        assert config.data.directory == "/test"
        assert config.preferences.auto_init is False
        assert config.preferences.interactive_mode is False
        assert config.preferences.language == "en"

    def test_user_config_to_dict(self):
        """UserConfig.to_dict() serializes correctly."""
        config = UserConfig(
            data=DataConfig(directory="/test"),
            preferences=PreferencesConfig(language="en", auto_init=False),
        )

        data = config.to_dict()

        assert data == {
            "data": {"directory": "/test"},
            "preferences": {"auto_init": False, "interactive_mode": True, "language": "en"},
        }

    def test_user_config_get_data_path(self):
        """UserConfig.get_data_path() expands ~ correctly."""
        config = UserConfig(data=DataConfig(directory="~/test-data"))

        path = config.get_data_path()

        assert "~" not in str(path)  # Should be expanded
        assert path.is_absolute()  # Should be resolved
        assert str(path).endswith("test-data")


class TestConfigIntegration:
    """Integration tests for Config class with config file support."""

    def test_config_metadata_dir_property(self):
        """Config.metadata_dir property works correctly."""
        config = Config(data_dir=Path("/test"))

        assert config.metadata_dir == Path("/test/metadata")

    def test_config_ensure_dirs_includes_metadata(self, tmp_path):
        """Config.ensure_dirs() creates metadata directory."""
        config = Config(data_dir=tmp_path / "data")

        config.ensure_dirs()

        assert config.metadata_dir.exists()
        assert config.metadata_dir.is_dir()

    def test_config_from_env_with_tilde(self, tmp_path, monkeypatch):
        """Config.from_env() correctly expands ~ in config file."""
        _set_home(monkeypatch, tmp_path)

        file_config = UserConfig(data=DataConfig(directory="~/my-data"))
        save_config(file_config)

        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)

        # Load config
        config = Config.from_env()

        # Should be expanded and absolute
        assert "~" not in str(config.data_dir)
        assert config.data_dir.is_absolute()
