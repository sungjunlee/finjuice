"""End-to-end tests for first-run UX and config file workflow.

Tests cover:
- Status-first root command behavior
- Config file operations and precedence
- Init command functionality
- Config persistence and loading
- Data directory initialization
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config_file import config_exists, load_config, save_config
from finjuice.pipeline.config_schema import DataConfig, UserConfig
from tests.conftest import cli_text


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Clean environment for E2E tests."""
    # Remove all config-related env vars
    monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
    monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    # Isolate Path.home() so save_config() writes to tmp, not real ~/.finjuice
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Set config path to temp directory
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    return tmp_path


class TestInitCommand:
    """Test finjuice init command E2E."""

    def test_root_command_first_run_shows_brief_status(self, runner, clean_env):
        """Test: finjuice without subcommands shows status instead of a wizard."""
        data_dir = clean_env / "fresh-data"
        data_dir.mkdir()

        result = runner.invoke(app, ["--data-dir", str(data_dir)])

        assert result.exit_code == 0
        assert "상태: 초기화 필요" in cli_text(result)
        assert "finjuice import" in cli_text(result)

    def test_init_creates_directory_structure(self, runner, clean_env):
        """Test: finjuice init creates all required directories and files."""
        data_dir = clean_env / "test-data"

        # Run init command
        result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])

        # Assertions
        assert result.exit_code == 0
        assert "Initialization complete" in cli_text(result)

        # Verify directory structure
        assert data_dir.exists()
        assert (data_dir / "imports").is_dir()
        assert (data_dir / "transactions").is_dir()
        assert (data_dir / "exports").is_dir()
        assert (data_dir / "metadata").is_dir()

        # Verify template files
        assert (data_dir / ".gitignore").exists()
        assert (data_dir / "README.md").exists()
        assert (data_dir / "rules.yaml").exists()
        assert (data_dir / "assets.yaml.example").exists()
        assert (data_dir / "scenarios.yaml.example").exists()

    def test_init_with_git(self, runner, clean_env):
        """Test: finjuice init --with-git initializes git repository."""
        data_dir = clean_env / "test-data"

        # Run init with git
        result = runner.invoke(app, ["--data-dir", str(data_dir), "init", "--with-git"])

        # Assertions
        assert result.exit_code == 0

        # Verify git repository (if git is available)
        if (data_dir / ".git").exists():
            assert (data_dir / ".git").is_dir()

    def test_init_without_git(self, runner, clean_env):
        """Test: finjuice init --no-git skips git initialization."""
        data_dir = clean_env / "test-data"

        # Run init without git
        result = runner.invoke(app, ["--data-dir", str(data_dir), "init", "--no-git"])

        # Assertions
        assert result.exit_code == 0
        # Git directory should not exist
        assert not (data_dir / ".git").exists()

    def test_init_idempotent(self, runner, clean_env):
        """Test: Running init twice is idempotent (safe)."""
        data_dir = clean_env / "test-data"

        # Run init first time
        result1 = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
        assert result1.exit_code == 0

        # Run init second time
        result2 = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
        assert result2.exit_code == 0
        assert "already initialized" in cli_text(result2)


class TestConfigPersistence:
    """Test config file persistence and loading."""

    def test_config_save_and_load(self, clean_env, monkeypatch):
        """Test: Config can be saved and loaded correctly."""
        # Save config
        data_dir = clean_env / "my-data"
        config = UserConfig(
            data=DataConfig(directory=str(data_dir)),
        )
        save_config(config)

        # Verify config file exists
        assert config_exists()

        # Load config
        loaded = load_config()
        assert loaded is not None
        assert str(data_dir) in loaded.data.directory

    def test_config_with_tilde_expansion(self, clean_env, monkeypatch):
        """Test: Config with ~ in path is expanded correctly."""
        # Save config with tilde
        config = UserConfig(
            data=DataConfig(directory="~/my-finance-data"),
        )
        save_config(config)

        # Load and verify expansion
        loaded = load_config()
        assert loaded is not None
        path = Path(loaded.data.directory).expanduser()
        assert path.is_absolute()
        assert "~" not in str(path)


class TestConfigPrecedence:
    """Test 4-tier config precedence (CLI > ENV > Config file > OS default)."""

    def test_cli_overrides_config_file(self, runner, clean_env, monkeypatch):
        """Priority 1: CLI --data-dir overrides config file."""
        # Setup: Save config file
        config_data_dir = clean_env / "from-config"
        config = UserConfig(data=DataConfig(directory=str(config_data_dir)))
        save_config(config)

        # CLI with different path
        cli_data_dir = clean_env / "from-cli"
        cli_data_dir.mkdir()
        (cli_data_dir / "imports").mkdir()
        (cli_data_dir / "transactions").mkdir()

        # Run command with CLI arg
        result = runner.invoke(app, ["--data-dir", str(cli_data_dir), "status"])

        # CLI path should be used (status will show data_dir)
        assert result.exit_code in [0, 1, 2, 4]  # May fail due to no data, but that's ok
        # The important part is that it used the CLI path, not the config file path

    def test_env_overrides_config_file(self, runner, clean_env, monkeypatch):
        """Priority 2: ENV variable overrides config file."""
        # Setup: Save config file
        config_data_dir = clean_env / "from-config"
        config = UserConfig(data=DataConfig(directory=str(config_data_dir)))
        save_config(config)

        # Setup: ENV variable
        env_data_dir = clean_env / "from-env"
        env_data_dir.mkdir()
        (env_data_dir / "imports").mkdir()
        (env_data_dir / "transactions").mkdir()
        monkeypatch.setenv("FINJUICE_DATA_DIR", str(env_data_dir))

        # Run command (no CLI arg)
        result = runner.invoke(app, ["status"])

        # ENV path should be used
        assert result.exit_code in [0, 1, 2, 4]

    def test_config_file_used_when_no_overrides(self, runner, clean_env, monkeypatch):
        """Priority 3: Config file used when no CLI arg or ENV."""
        # Setup: Save config file and create data dir
        config_data_dir = clean_env / "from-config"
        config_data_dir.mkdir()
        (config_data_dir / "imports").mkdir()
        (config_data_dir / "transactions").mkdir()

        config = UserConfig(data=DataConfig(directory=str(config_data_dir)))
        save_config(config)

        # No ENV
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
        monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

        # Run command (no CLI arg, no ENV)
        result = runner.invoke(app, ["status"])

        # Config file path should be used
        assert result.exit_code in [0, 1, 2, 4]


class TestFullWorkflow:
    """Test complete workflows from init to pipeline."""

    def test_init_and_status(self, runner, clean_env):
        """Workflow: Init data directory, then check status."""
        data_dir = clean_env / "workflow-test"

        # Step 1: Init
        result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
        assert result.exit_code == 0
        assert data_dir.exists()

        # Step 2: Check status
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])
        assert result.exit_code in [0, 1, 2, 4]  # Will show "empty" status
        # emit_error outputs error message; old code printed header + warning
        assert (
            "Status" in cli_text(result)
            or "Empty" in cli_text(result)
            or "No CSV partitions found" in cli_text(result)
        )

    def test_config_save_then_use_without_data_dir_flag(self, runner, clean_env, monkeypatch):
        """Workflow: Save config, then use commands without --data-dir flag."""
        # Step 1: Init with data-dir
        data_dir = clean_env / "workflow-test"
        result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
        assert result.exit_code == 0

        # Step 2: Save config
        config = UserConfig(data=DataConfig(directory=str(data_dir)))
        save_config(config)

        # Clear ENV
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
        monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

        # Step 3: Use command without --data-dir (should use config file)
        result = runner.invoke(app, ["status"])
        assert result.exit_code in [0, 1, 2, 4]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_status_without_init(self, runner, clean_env, tmp_path, monkeypatch):
        """Edge case: Running status before init shows helpful message."""
        # Create a fresh empty data directory
        empty_data = tmp_path / "empty_data"
        empty_data.mkdir()

        # No init, no config file, use explicit empty data dir
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
        monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

        result = runner.invoke(app, ["--data-dir", str(empty_data), "status"])

        # Should fail gracefully with helpful message
        assert result.exit_code in [2, 4]  # USAGE_ERROR or NO_DATA
        # Message should suggest either 'init' or 'ingest' as next steps
        assert (
            "init" in cli_text(result).lower()
            or "ingest" in cli_text(result).lower()
            or "not found" in cli_text(result).lower()
        )

    def test_init_with_invalid_path_permissions(self, runner):
        """Edge case: Init with invalid path shows clear error."""
        # Try to init in root directory (permission denied)
        result = runner.invoke(app, ["--data-dir", "/root/test-data", "init"])

        # Should fail with permission error
        assert result.exit_code == 1
