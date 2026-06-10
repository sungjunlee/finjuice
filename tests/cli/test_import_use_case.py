"""Tests for the focused import command use case."""

from pathlib import Path
from unittest.mock import Mock

from finjuice.pipeline.cli.commands.import_cmd import run_import
from finjuice.pipeline.cli.commands.import_cmd.options import ImportOptions
from finjuice.pipeline.cli.commands.import_cmd.result import ImportResult
from finjuice.pipeline.config import Config


def test_run_import_returns_result_for_json_dry_run(tmp_path: Path) -> None:
    """The import use case should compute dry-run JSON without copying files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n")
    source_dir = tmp_path / "downloads"
    source_dir.mkdir()
    xlsx_file = source_dir / "preview.xlsx"
    xlsx_file.write_bytes(b"PK\x03\x04mock")

    options = ImportOptions(
        ctx=Mock(),
        config=Config(data_dir=data_dir),
        files=(xlsx_file,),
        file=None,
        force=False,
        dry_run=True,
        password=None,
        json_output=True,
    )

    result = run_import(options)

    assert isinstance(result, ImportResult)
    assert result.payload == {
        "files_processed": 1,
        "files_skipped": 0,
        "errors": 0,
        "dry_run": True,
    }
    assert not (data_dir / "imports" / "preview.xlsx").exists()
