"""Tests for first-run auto-setup during finjuice import."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.import_cmd import is_first_run
from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _pipeline_summary(data_dir: Path) -> dict[str, object]:
    """Build a minimal pipeline summary for mocked imports."""
    return {
        "ingest": {"inserted": 1},
        "tag": {"tagged": 1, "coverage_pct": 100.0},
        "transfer": {"pairs": 0},
        "master_path": data_dir / "exports" / "master.xlsx",
    }


class TestFirstRunDetection:
    """Tests for first-run detection helper."""

    def test_is_first_run_missing_dir(self, tmp_path: Path) -> None:
        assert is_first_run(tmp_path / "nonexistent") is True

    def test_is_first_run_missing_rules(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert is_first_run(tmp_path) is True

    def test_is_not_first_run(self, tmp_path: Path) -> None:
        (tmp_path / "rules.yaml").write_text("version: 1\nrules: []")
        assert is_first_run(tmp_path) is False


class TestImportFirstRun:
    """Integration tests for first-run auto-init via import."""

    def test_import_auto_initializes_on_first_run(self, tmp_path: Path) -> None:
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        xlsx_file = downloads_dir / "first.xlsx"
        xlsx_file.write_bytes(b"PK\x03\x04mock")

        data_dir = tmp_path / "data"

        with (
            patch(
                "finjuice.pipeline.cli.commands.init_cmd.init_git_repository",
                return_value=False,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ),
        ):
            result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_file)])

        normalized_output = "".join(result.output.split())

        assert result.exit_code == 0
        assert (data_dir / "rules.yaml").exists()
        assert (data_dir / "imports" / "first.xlsx").exists()
        assert "데이터 디렉터리 초기화됨" in result.output
        assert "초기 설정" in result.output
        assert "데이터 위치" in result.output
        assert str(data_dir) in normalized_output

    def test_second_import_skips_first_run_setup_message(self, tmp_path: Path) -> None:
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        first_file = downloads_dir / "first.xlsx"
        second_file = downloads_dir / "second.xlsx"
        first_file.write_bytes(b"PK\x03\x04first")
        second_file.write_bytes(b"PK\x03\x04second")

        data_dir = tmp_path / "data"

        with (
            patch(
                "finjuice.pipeline.cli.commands.init_cmd.init_git_repository",
                return_value=False,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ),
        ):
            first_result = runner.invoke(
                app, ["--data-dir", str(data_dir), "import", str(first_file)]
            )
            second_result = runner.invoke(
                app, ["--data-dir", str(data_dir), "import", str(second_file)]
            )

        assert first_result.exit_code == 0
        assert second_result.exit_code == 0
        assert "데이터 디렉터리 초기화됨" in first_result.output
        assert "초기 설정" in first_result.output
        assert "데이터 디렉터리 초기화됨" not in second_result.output
        assert "초기 설정" not in second_result.output
        assert (data_dir / "imports" / "second.xlsx").exists()


class TestInitHelp:
    """Tests for init help text."""

    def test_init_help_mentions_import_auto_setup(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FINJUICE_DATA_DIR", str(tmp_path / "data"))

        result = runner.invoke(app, ["init", "--help"])

        assert result.exit_code == 0
        normalized_output = " ".join(result.output.split())
        assert "Most users should use `finjuice import`" in normalized_output
        assert "handles setup automatically." in normalized_output
