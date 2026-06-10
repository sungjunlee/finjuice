"""Tests for `finjuice import --json` output."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _pipeline_summary(data_dir: Path) -> dict[str, object]:
    """Build a mocked pipeline summary for import command tests."""
    return {
        "ingest": {"inserted": 7, "updated": 0},
        "tag": {"tagged": 6, "untagged": 1, "coverage_pct": 85.7},
        "transfer": {"pairs": 2, "paired": 4},
        "export": {"rows": 7, "reports": 4},
        "master_path": data_dir / "exports" / "master.xlsx",
        "steps": {
            "ingest": {
                "command": "ingest",
                "summary": {
                    "files_processed": 1,
                    "new_transactions": 7,
                    "updated": 0,
                    "failed": 0,
                    "failed_files": [],
                },
            },
            "tag": {
                "status": "ok",
                "tagged": 6,
                "untagged": 1,
                "coverage_pct": 85.7,
            },
            "transfer": {"status": "ok", "pairs_found": 2, "pairs_linked": 4},
            "export": {"command": "export", "transaction_count": 7, "output_files": []},
        },
    }


class TestImportJsonOutput:
    """Tests for machine-readable import output."""

    def test_import_help_includes_json_flag(self) -> None:
        """`finjuice import --help` should expose the JSON flag."""
        result = runner.invoke(app, ["import", "--help"])

        assert result.exit_code == 0
        assert "--json" in result.output

    def test_import_json_success(self, tmp_path: Path) -> None:
        """`import --json` should emit a structured success payload."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_path = source_dir / "banksalad.xlsx"
        xlsx_path.write_bytes(b"PK\x03\x04mock xlsx content")

        imported_dest = data_dir / "imports" / xlsx_path.name
        import_result = {"imported": [(xlsx_path, imported_dest)], "skipped": [], "errors": []}

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.import_xlsx_files",
                return_value=import_result,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ) as mock_pipeline,
        ):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--json", str(xlsx_path)],
            )

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["files_processed"] == 1
        assert payload["files_skipped"] == 0
        assert payload["errors"] == 0
        assert payload["transactions_inserted"] == 7
        assert payload["pipeline_result"]["export"]["reports"] == 4
        assert payload["pipeline_result"]["tag"]["tagged"] == 6
        assert payload["steps"]["ingest"]["summary"]["new_transactions"] == 7
        assert "Importing" not in result.output
        assert mock_pipeline.call_args.kwargs["emit_text"] is False

    def test_import_json_zip_without_password_fails_fast(self, tmp_path: Path) -> None:
        """`import --json` should return JSON instead of prompting for ZIP passwords."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        zip_path = tmp_path / "downloads" / "banksalad.zip"
        zip_path.parent.mkdir()
        zip_path.write_bytes(b"PK\x03\x04mock zip content")

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd._zip_requires_password",
                return_value=True,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.extract_xlsx_from_zip"
            ) as mock_extract,
        ):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--json", str(zip_path)],
            )

        # Assert
        assert result.exit_code == 3
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["error"]["code"] == "VALIDATION_FAILED"
        assert "ZIP 암호 필요" in payload["error"]["message"]
        assert payload["exit_code"] == 3
        mock_extract.assert_not_called()

    def test_import_json_zip_uses_password_env_without_prompt(self, tmp_path: Path) -> None:
        """`FINJUICE_ZIP_PASSWORD` should drive headless ZIP import in JSON mode."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        zip_path = source_dir / "banksalad.zip"
        zip_path.write_bytes(b"PK\x03\x04mock zip content")
        extracted_dir = tmp_path / "extracted"
        extracted_dir.mkdir()
        extracted_xlsx = extracted_dir / "banksalad.xlsx"
        extracted_xlsx.write_bytes(b"PK\x03\x04mock xlsx content")

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd._zip_requires_password",
                return_value=True,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.extract_xlsx_from_zip",
                return_value=extracted_xlsx,
            ) as mock_extract,
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ) as mock_pipeline,
        ):
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--json", str(zip_path)],
                env={"FINJUICE_ZIP_PASSWORD": "1234"},
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["files_processed"] == 1
        assert payload["errors"] == 0
        mock_extract.assert_called_once_with(
            zip_path.resolve(),
            password="1234",
            interactive=False,
            emit_text=False,
        )
        assert mock_pipeline.call_args.kwargs["emit_text"] is False

    def test_import_json_unencrypted_zip_imports_normally(self, tmp_path: Path) -> None:
        """Unencrypted ZIP files should still import in JSON mode."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        zip_path = source_dir / "banksalad.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("banksalad.xlsx", b"PK\x03\x04mock xlsx content")

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ) as mock_pipeline,
        ):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--json", str(zip_path)],
            )

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["files_processed"] == 1
        assert payload["errors"] == 0
        assert payload["transactions_inserted"] == 7
        assert (data_dir / "imports" / "banksalad.xlsx").exists()
        assert mock_pipeline.call_args.kwargs["emit_text"] is False

    def test_import_json_dry_run(self, tmp_path: Path) -> None:
        """`import --json --dry-run` should emit a partial structured payload."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_path = source_dir / "preview.xlsx"
        xlsx_path.write_bytes(b"PK\x03\x04mock xlsx content")

        imported_dest = data_dir / "imports" / xlsx_path.name
        import_result = {"imported": [(xlsx_path, imported_dest)], "skipped": [], "errors": []}

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.import_xlsx_files",
                return_value=import_result,
            ),
            patch("finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline") as mock_pipeline,
        ):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--dry-run", "--json", str(xlsx_path)],
            )

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["files_processed"] == 1
        assert payload["files_skipped"] == 0
        assert payload["errors"] == 0
        assert payload["dry_run"] is True
        mock_pipeline.assert_not_called()

    def test_import_json_dry_run_zip_counts_pending_archive(self, tmp_path: Path) -> None:
        """`import --json --dry-run` should count ZIP inputs in the structured preview."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        zip_path = source_dir / "preview.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("preview.xlsx", b"PK\x03\x04mock xlsx content")

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch("finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline") as mock_pipeline,
        ):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--dry-run", "--json", str(zip_path)],
            )

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["files_processed"] == 1
        assert payload["files_skipped"] == 0
        assert payload["errors"] == 0
        assert payload["dry_run"] is True
        mock_pipeline.assert_not_called()

    def test_import_text_mode_is_unchanged(self, tmp_path: Path) -> None:
        """`import` without `--json` should keep the existing Rich-style output."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        xlsx_path = source_dir / "human.xlsx"
        xlsx_path.write_bytes(b"PK\x03\x04mock xlsx content")

        imported_dest = data_dir / "imports" / xlsx_path.name
        import_result = {"imported": [(xlsx_path, imported_dest)], "skipped": [], "errors": []}

        with (
            patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.import_xlsx_files",
                return_value=import_result,
            ),
            patch(
                "finjuice.pipeline.cli.commands.import_cmd.run_full_pipeline",
                return_value=_pipeline_summary(data_dir),
            ) as mock_pipeline,
        ):
            # Act
            result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(xlsx_path)])

        # Assert
        assert result.exit_code == 0
        assert "복사됨: human.xlsx" in result.output
        assert "완료!" in result.output
        assert '"_meta"' not in result.output
        assert mock_pipeline.call_args.kwargs["emit_text"] is True

    def test_import_text_mode_zip_failure_keeps_specific_message_only(self, tmp_path: Path) -> None:
        """Human mode should not append a second generic ZIP extraction error."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        zip_path = tmp_path / "downloads" / "broken.zip"
        zip_path.parent.mkdir()
        zip_path.write_bytes(b"not a valid zip")

        with patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False):
            # Act
            result = runner.invoke(app, ["--data-dir", str(data_dir), "import", str(zip_path)])

        # Assert
        assert result.exit_code == 1
        assert "손상된 ZIP 파일: broken.zip" in result.output
        assert "ZIP extraction failed: broken.zip" not in result.output

    def test_import_json_zip_policy_failure_returns_structured_error(self, tmp_path: Path) -> None:
        """ZIP validation failures should use the import JSON error envelope."""
        # Arrange
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        source_dir = tmp_path / "downloads"
        source_dir.mkdir()
        zip_path = source_dir / "banksalad.zip"
        sensitive_member = "private_notes.csv"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("banksalad.xlsx", b"PK\x03\x04mock xlsx content")
            zf.writestr(sensitive_member, "a,b,c")

        with patch("finjuice.pipeline.cli.commands.import_cmd.is_first_run", return_value=False):
            # Act
            result = runner.invoke(
                app,
                ["--data-dir", str(data_dir), "import", "--json", str(zip_path)],
            )

        # Assert
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "import"
        assert payload["error"]["code"] == "GENERAL_ERROR"
        assert "ZIP 추출 실패: banksalad.zip" in payload["error"]["message"]
        assert sensitive_member not in result.output
