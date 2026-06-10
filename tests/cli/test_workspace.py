"""Tests for finjuice workspace command (Issue #65)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


def fail_on_interactive_prompt(*args: object, **kwargs: object) -> None:
    """Fail tests when an interactive prompt is unexpectedly invoked."""
    raise AssertionError("interactive prompt should not be called")


class TestWorkspaceCreate:
    """Test finjuice workspace create command."""

    def test_create_workspace_basic(self, tmp_path: Path) -> None:
        """Test basic workspace creation with symlinks."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        assert workspace_dir.exists()

        # Check symlinks were created
        assert (workspace_dir / "imports").is_symlink()
        assert (workspace_dir / "exports").is_symlink()
        assert (workspace_dir / "transactions").is_symlink()
        assert (workspace_dir / "rules.yaml").is_symlink()

        # Check symlinks point to correct targets
        assert (workspace_dir / "imports").resolve() == (data_dir / "imports").resolve()
        assert (workspace_dir / "exports").resolve() == (data_dir / "exports").resolve()

    def test_create_workspace_writes_metadata(self, tmp_path: Path) -> None:
        """Test that workspace metadata file is created."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        metadata_file = workspace_dir / ".finjuice-workspace"
        assert metadata_file.exists()

        metadata = yaml.safe_load(metadata_file.read_text())
        assert metadata["version"] == 1
        assert "data_dir" in metadata
        assert "created_at" in metadata

    def test_create_workspace_writes_readme(self, tmp_path: Path) -> None:
        """Test that README.md is created in workspace."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        readme_file = workspace_dir / "README.md"
        assert readme_file.exists()
        content = readme_file.read_text()
        assert "workspace" in content.lower() or "finjuice" in content.lower()

    def test_create_workspace_already_exists(self, tmp_path: Path) -> None:
        """Test error when workspace directory already exists with content."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        (workspace_dir / "existing_file.txt").write_text("existing content")

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "exist" in output or "not empty" in output

    def test_create_workspace_missing_data_directories(self, tmp_path: Path) -> None:
        """Test error when data directories don't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Don't create imports/, exports/, etc.

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "does not exist" in output or "missing" in output

    def test_create_workspace_shows_success_message(self, tmp_path: Path) -> None:
        """Test that success message shows created paths."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        output = cli_text(result).lower()
        assert "created" in output or "workspace" in output

    def test_create_workspace_rejects_program_repo_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test workspace symlinks are not created inside the program repository."""
        # Arrange
        repo_root = tmp_path / "finjuice"
        repo_root.mkdir()
        data_dir = tmp_path / "private-data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")
        workspace_dir = repo_root / "workspace"
        monkeypatch.setattr("finjuice.pipeline.config._get_program_repo_root", lambda: repo_root)

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 1
        assert "program repository" in cli_text(result)
        assert not workspace_dir.exists()


class TestWorkspaceList:
    """Test finjuice workspace list command."""

    def test_list_workspaces_empty(self, tmp_path: Path) -> None:
        """Test listing workspaces when none exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "list"],
        )

        # Assert
        assert result.exit_code == 0
        output = cli_text(result).lower()
        assert "no workspace" in output or "none" in output or "0" in output

    def test_list_workspaces_shows_active(self, tmp_path: Path) -> None:
        """Test listing active workspaces."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Create workspace first
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "list"],
        )

        # Assert
        assert result.exit_code == 0
        output = cli_text(result)
        assert str(workspace_dir) in output or "workspace" in output.lower()


class TestWorkspaceRemove:
    """Test finjuice workspace remove command."""

    def test_remove_workspace_basic(self, tmp_path: Path) -> None:
        """Test removing a workspace."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(workspace_dir), "--force"],
        )

        # Assert
        assert result.exit_code == 0
        assert not workspace_dir.exists()

    def test_remove_workspace_yes_skips_confirmation(self, tmp_path: Path, monkeypatch) -> None:
        """Test removing a workspace with `--yes`."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )
        monkeypatch.setattr(
            "finjuice.pipeline.cli.commands.workspace_cmd.typer.confirm",
            fail_on_interactive_prompt,
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(workspace_dir), "--yes"],
        )

        # Assert
        assert result.exit_code == 0
        assert not workspace_dir.exists()

    def test_remove_workspace_preserves_data(self, tmp_path: Path) -> None:
        """Test that removing workspace doesn't delete actual data."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        # Add a file to imports
        test_file = imports_dir / "test.xlsx"
        test_file.write_bytes(b"test content")

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(workspace_dir), "--force"],
        )

        # Assert
        assert result.exit_code == 0
        assert not workspace_dir.exists()
        # Data should be preserved
        assert test_file.exists()
        assert test_file.read_bytes() == b"test content"

    def test_remove_workspace_not_found(self, tmp_path: Path) -> None:
        """Test error when workspace doesn't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        workspace_dir = tmp_path / "nonexistent"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(workspace_dir), "--force"],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "does not exist" in output

    def test_remove_workspace_not_a_workspace(self, tmp_path: Path) -> None:
        """Test error when directory is not a workspace."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        not_workspace_dir = tmp_path / "regular_dir"
        not_workspace_dir.mkdir()
        (not_workspace_dir / "some_file.txt").write_text("content")

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(not_workspace_dir), "--force"],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert (
            ("not a" in output and "workspace" in output)
            or "invalid" in output
            or "metadata" in output
        )


class TestWorkspaceVerify:
    """Test finjuice workspace verify command."""

    def test_verify_workspace_valid(self, tmp_path: Path) -> None:
        """Test verifying a valid workspace."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "verify", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        output = cli_text(result).lower()
        assert "valid" in output or "passed" in output or "ok" in output

    def test_verify_workspace_broken_symlink(self, tmp_path: Path) -> None:
        """Test verifying workspace with broken symlink."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Break the symlink by removing target
        import shutil

        shutil.rmtree(data_dir / "imports")

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "verify", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "broken" in output or "invalid" in output or "failed" in output

    def test_verify_workspace_not_found(self, tmp_path: Path) -> None:
        """Test error when workspace doesn't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        workspace_dir = tmp_path / "nonexistent"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "verify", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "does not exist" in output


class TestWorkspaceOpen:
    """Test finjuice workspace open command."""

    @patch("subprocess.run")
    def test_open_workspace(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Test opening workspace in file manager."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        mock_run.return_value = MagicMock(returncode=0)

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "open", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert str(workspace_dir) in call_args


class TestWorkspaceRegistry:
    """Test workspace registry functionality."""

    def test_workspace_registered_on_create(self, tmp_path: Path) -> None:
        """Test that workspace is registered in global registry."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")
        (data_dir / "metadata").mkdir()

        workspace_dir = tmp_path / "workspace"

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Assert
        assert result.exit_code == 0
        registry_file = data_dir / "metadata" / "workspaces.yaml"
        assert registry_file.exists()

        registry = yaml.safe_load(registry_file.read_text())
        assert "workspaces" in registry
        assert len(registry["workspaces"]) >= 1

    def test_workspace_unregistered_on_remove(self, tmp_path: Path) -> None:
        """Test that workspace is unregistered when removed."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "transactions").mkdir()
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []")
        (data_dir / "metadata").mkdir()

        workspace_dir = tmp_path / "workspace"

        # Create workspace
        runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "create", str(workspace_dir)],
        )

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "workspace", "remove", str(workspace_dir), "--force"],
        )

        # Assert
        assert result.exit_code == 0
        registry_file = data_dir / "metadata" / "workspaces.yaml"
        if registry_file.exists():
            registry = yaml.safe_load(registry_file.read_text())
            # Workspace should be removed or marked as removed
            workspace_paths = [w.get("path") for w in registry.get("workspaces", [])]
            assert str(workspace_dir) not in workspace_paths
