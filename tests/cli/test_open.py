"""Tests for finjuice open command (Issue #64)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


class TestOpenCommand:
    """Test finjuice open command for opening data directories and files."""

    def test_open_default_opens_data_dir(self, tmp_path: Path, monkeypatch) -> None:
        """Test that 'finjuice open' opens data directory."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert str(data_dir) in call_args

    def test_open_imports_directory(self, tmp_path: Path) -> None:
        """Test 'finjuice open imports' opens imports directory."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        imports_dir = data_dir / "imports"
        imports_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "imports"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "imports" in call_args[-1]

    def test_open_exports_directory(self, tmp_path: Path) -> None:
        """Test 'finjuice open exports' opens exports directory."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        exports_dir = data_dir / "exports"
        exports_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "exports"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "exports" in call_args[-1]

    def test_open_reports_directory(self, tmp_path: Path) -> None:
        """Test 'finjuice open reports' opens reports directory."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        reports_dir = data_dir / "exports" / "reports"
        reports_dir.mkdir(parents=True)

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "reports"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "reports" in call_args[-1]

    def test_open_transactions_directory(self, tmp_path: Path) -> None:
        """Test 'finjuice open transactions' opens transactions directory."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        tx_dir = data_dir / "transactions"
        tx_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "transactions"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "transactions" in call_args[-1]

    def test_open_tx_alias(self, tmp_path: Path) -> None:
        """Test 'finjuice open tx' is an alias for transactions."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        tx_dir = data_dir / "transactions"
        tx_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "tx"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "transactions" in call_args[-1]

    def test_open_rules_file(self, tmp_path: Path) -> None:
        """Test 'finjuice open rules' opens rules.yaml file."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        rules_file = data_dir / "rules.yaml"
        rules_file.write_text("version: 1\nrules: []")

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "rules"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "rules.yaml" in call_args[-1]

    def test_open_master_file(self, tmp_path: Path) -> None:
        """Test 'finjuice open master' opens latest master file."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        exports_dir = data_dir / "exports"
        exports_dir.mkdir()
        # Create multiple master files
        (exports_dir / "master_20241001.xlsx").write_bytes(b"old")
        (exports_dir / "master_20241201.xlsx").write_bytes(b"new")
        (exports_dir / "master_20241101.xlsx").write_bytes(b"mid")

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "master"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        # Should open latest (20241201)
        assert "master_20241201.xlsx" in call_args[-1]

    def test_open_directory_not_found(self, tmp_path: Path) -> None:
        """Test error when directory doesn't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Don't create imports directory

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "imports"])

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "does not exist" in output

    def test_open_rules_not_found(self, tmp_path: Path) -> None:
        """Test error when rules.yaml doesn't exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Don't create rules.yaml

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "rules"])

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "does not exist" in output

    def test_open_master_not_found(self, tmp_path: Path) -> None:
        """Test error when no master files exist."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        exports_dir = data_dir / "exports"
        exports_dir.mkdir()
        # Don't create any master files

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "master"])

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "not found" in output or "no master" in output

    def test_open_invalid_target(self, tmp_path: Path) -> None:
        """Test error when target is invalid."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "invalid"])

        # Assert
        assert result.exit_code == 1
        output = cli_text(result).lower()
        assert "invalid" in output or "unknown" in output

    @patch("platform.system", return_value="Darwin")
    def test_open_uses_open_on_macos(self, mock_platform: MagicMock, tmp_path: Path) -> None:
        """Test that 'open' command is used on macOS."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "open"

    @patch("platform.system", return_value="Linux")
    def test_open_uses_xdg_open_on_linux(self, mock_platform: MagicMock, tmp_path: Path) -> None:
        """Test that 'xdg-open' command is used on Linux."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "xdg-open"

    @patch("platform.system", return_value="Windows")
    def test_open_uses_explorer_on_windows(self, mock_platform: MagicMock, tmp_path: Path) -> None:
        """Test that 'explorer' command is used on Windows."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open"])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "explorer"

    def test_open_dot_alias(self, tmp_path: Path) -> None:
        """Test 'finjuice open .' is an alias for data root."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Act
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["--data-dir", str(data_dir), "open", "."])

        # Assert
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert str(data_dir) in call_args[-1]
