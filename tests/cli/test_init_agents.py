"""
Tests for CLI init --with-agents and update-agents commands.

Tests:
- finjuice init --with-agents: Initialize with AGENTS.md
- finjuice update-agents: Update AGENTS.md template
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.fixture
def empty_data_dir(tmp_path: Path) -> Path:
    """Create an empty data directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def initialized_data_dir(tmp_path: Path) -> Path:
    """Create an initialized data directory with AGENTS.md."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # Create minimal structure
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports" / "reports").mkdir(parents=True)

    # Create files
    (data_dir / ".gitignore").write_text("*.xlsx\n")
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n")
    (data_dir / "AGENTS.md").write_text("# Old AGENTS.md content\n")

    return data_dir


class TestInitWithAgents:
    """Tests for finjuice init --with-agents."""

    def test_init_with_agents_creates_agents_md(self, tmp_path: Path) -> None:
        """Test that --with-agents creates AGENTS.md."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--with-agents", "--no-git"],
        )

        assert result.exit_code == 0
        agents_file = data_dir / "AGENTS.md"
        assert agents_file.exists()
        assert "AGENTS.md" in result.output

    def test_init_with_agents_content(self, tmp_path: Path) -> None:
        """Test that AGENTS.md has correct content."""
        data_dir = tmp_path / "new_data"

        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--with-agents", "--no-git"],
        )

        agents_file = data_dir / "AGENTS.md"
        content = agents_file.read_text()

        # Check key sections
        assert "# finjuice" in content
        assert "external agent guidance" in content.lower()
        assert "finjuice" in content
        assert "rules.yaml" in content
        assert "SKILL.md" in content
        assert "## CLI Boundaries" in content

    def test_init_without_agents_no_agents_md(self, tmp_path: Path) -> None:
        """Test that init without --with-agents doesn't create AGENTS.md."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        agents_file = data_dir / "AGENTS.md"
        assert not agents_file.exists()

    def test_init_creates_goals_yaml_from_packaged_template(self, tmp_path: Path) -> None:
        """Test that init seeds goals.yaml through the packaged template flow."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        goals_file = data_dir / "goals.yaml"
        assert goals_file.exists()

        content = goals_file.read_text()
        assert "monthly_budget:" in content
        assert "total: 2000000" in content
        assert "categories:" in content

    def test_init_creates_scenarios_yaml_example(self, tmp_path: Path) -> None:
        """Test that init seeds scenarios.yaml.example through the packaged template flow."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        scenarios_file = data_dir / "scenarios.yaml.example"
        assert scenarios_file.exists()

        content = scenarios_file.read_text()
        assert "default_savings_per_month" in content
        assert "asset_returns:" in content
        assert "lifecycle_events:" in content

    def test_init_with_agents_shows_tip(self, tmp_path: Path) -> None:
        """Test that init with agents shows AI integration tip."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--with-agents", "--no-git"],
        )

        assert "AI Integration" in result.output  # Matches actual emoji + text format

    def test_init_shows_directory_path(self, tmp_path: Path) -> None:
        """Test that init shows initialized data directory path."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        normalized_output = "".join(result.output.split())

        assert result.exit_code == 0
        assert "Initialized data directory:" in result.output
        # Rich may wrap long temp paths mid-token; remove whitespace before asserting.
        assert str(data_dir) in normalized_output

    def test_init_shows_save_config_tip(self, tmp_path: Path) -> None:
        """Test that init shows --save-config tip for users."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        # New format shows tip about --save-config instead of "Quick access:"
        assert "--save-config" in result.output
        assert "Tip" in result.output

    def test_init_output_structure(self, tmp_path: Path) -> None:
        """Test that init output has logical structure."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        output = result.output

        # Check output sections appear in order
        complete_pos = output.find("Initialization complete!")
        directory_pos = output.find("Initialized data directory:")
        steps_pos = output.find("Next steps:")
        tip_pos = output.find("Tip")

        # All sections should exist
        assert complete_pos >= 0
        assert directory_pos >= 0
        assert steps_pos >= 0
        assert tip_pos >= 0

        # Should appear in logical order
        assert complete_pos < directory_pos < steps_pos < tip_pos

    def test_init_with_save_config(self, tmp_path: Path, monkeypatch) -> None:
        """Test that --save-config saves the config file."""
        data_dir = tmp_path / "new_data"

        # Isolate Path.home() so save_config writes to tmp, not real ~/.finjuice
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git", "--save-config"],
        )

        assert result.exit_code == 0
        assert "Config saved" in result.output or "config" in result.output.lower()
        # Verify config was written to isolated path, not real home
        assert (fake_home / ".finjuice" / "config.toml").exists()

    def test_init_without_save_config_shows_tip(self, tmp_path: Path) -> None:
        """Test that init without --save-config shows the tip."""
        data_dir = tmp_path / "new_data"

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "init", "--no-git"],
        )

        assert result.exit_code == 0
        assert "--save-config" in result.output


class TestUpdateAgents:
    """Tests for finjuice update-agents command."""

    def test_update_agents_success(self, initialized_data_dir: Path) -> None:
        """Test that update-agents updates AGENTS.md."""
        result = runner.invoke(
            app,
            ["--data-dir", str(initialized_data_dir), "update-agents"],
        )

        assert result.exit_code == 0
        assert "✅ AGENTS.md updated" in result.output

    def test_update_agents_creates_backup(self, initialized_data_dir: Path) -> None:
        """Test that update-agents creates a backup."""
        original_content = (initialized_data_dir / "AGENTS.md").read_text()

        result = runner.invoke(
            app,
            ["--data-dir", str(initialized_data_dir), "update-agents"],
        )

        assert result.exit_code == 0
        backup_file = initialized_data_dir / "AGENTS.md.bak"
        assert backup_file.exists()
        assert backup_file.read_text() == original_content

    def test_update_agents_replaces_content(self, initialized_data_dir: Path) -> None:
        """Test that update-agents replaces AGENTS.md content."""
        runner.invoke(
            app,
            ["--data-dir", str(initialized_data_dir), "update-agents"],
        )

        agents_file = initialized_data_dir / "AGENTS.md"
        content = agents_file.read_text()

        # Should have new template content
        assert "# finjuice" in content
        assert "## CLI Boundaries" in content
        assert "Old AGENTS.md" not in content

    def test_update_agents_not_found(self, empty_data_dir: Path) -> None:
        """Test update-agents when AGENTS.md doesn't exist."""
        # Remove AGENTS.md if it exists
        agents_file = empty_data_dir / "AGENTS.md"
        if agents_file.exists():
            agents_file.unlink()

        result = runner.invoke(
            app,
            ["--data-dir", str(empty_data_dir), "update-agents"],
        )

        assert result.exit_code == 1
        normalized_output = " ".join(result.output.lower().split())
        assert "not found" in normalized_output
        # Rich console width can wrap this command across lines in CI.
        assert "init --with-agents" in normalized_output
