"""Tests for the focused import command use case."""

from pathlib import Path
from unittest.mock import Mock, patch

from finjuice.pipeline.cli.commands.import_cmd import import_xlsx_files, run_import
from finjuice.pipeline.cli.commands.import_cmd.options import ImportOptions
from finjuice.pipeline.cli.commands.import_cmd.result import ImportResult
from finjuice.pipeline.cli.commands.import_cmd.use_case import (
    ImportDependencies,
)
from finjuice.pipeline.cli.commands.import_cmd.use_case import (
    run_import as run_import_use_case,
)
from finjuice.pipeline.config import Config


def _options(
    tmp_path: Path,
    files: tuple[Path, ...],
    *,
    dry_run: bool = False,
    json_output: bool = True,
    force: bool = False,
) -> ImportOptions:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n")
    return ImportOptions(
        ctx=Mock(),
        config=Config(data_dir=data_dir),
        files=files,
        file=None,
        force=force,
        dry_run=dry_run,
        password=None,
        json_output=json_output,
    )


def _pipeline_summary() -> dict[str, object]:
    return {
        "ingest": {"inserted": 0, "updated": 0, "files": 1, "failed": 0},
        "tag": {"total": 0, "tagged": 0, "untagged": 0, "coverage_pct": 0.0},
        "transfer": {"pairs": 0, "paired": 0},
        "export": {"rows": 0, "reports": 0},
        "steps": {
            "ingest": {
                "summary": {
                    "files_processed": 1,
                    "new_transactions": 0,
                    "updated": 0,
                    "failed": 0,
                    "failed_files": [],
                }
            },
            "tag": {"total": 0, "tagged": 0, "untagged": 0, "coverage_pct": 0.0},
            "transfer": {"pairs_found": 0, "pairs_linked": 0},
            "export": {"transaction_count": 0, "output_files": []},
        },
    }


def _ingest_batch_summary() -> dict[str, object]:
    return {
        "files": 1,
        "inserted": 0,
        "updated": 0,
        "failed": 0,
        "failed_files": [],
    }


def test_run_import_returns_result_for_json_dry_run(tmp_path: Path) -> None:
    """The import use case should compute dry-run JSON without copying files."""
    source_dir = tmp_path / "downloads"
    source_dir.mkdir()
    xlsx_file = source_dir / "preview.xlsx"
    xlsx_file.write_bytes(b"PK\x03\x04mock")

    result = run_import(_options(tmp_path, (xlsx_file,), dry_run=True))

    assert isinstance(result, ImportResult)
    assert result.payload == {
        "files_processed": 1,
        "files_skipped": 0,
        "errors": 0,
        "dry_run": True,
    }
    assert not (tmp_path / "data" / "imports" / "preview.xlsx").exists()


def test_run_import_dry_run_json_payload_unchanged_when_file_already_in_imports(
    tmp_path: Path,
) -> None:
    """Dry-run JSON keys stay files_processed/files_skipped/errors/dry_run."""
    options = _options(tmp_path, (), dry_run=True)
    staged = options.config.import_dir
    staged.mkdir(parents=True)
    xlsx_file = staged / "preview.xlsx"
    xlsx_file.write_bytes(b"PK\x03\x04mock")
    options = _options(tmp_path, (xlsx_file,), dry_run=True)

    result = run_import(options)

    assert result.payload == {
        "files_processed": 0,
        "files_skipped": 1,
        "errors": 0,
        "dry_run": True,
    }
    assert set(result.payload) == {"files_processed", "files_skipped", "errors", "dry_run"}


def test_run_import_already_in_imports_runs_targeted_ingest(tmp_path: Path) -> None:
    """A path already under imports/ still runs the pipeline for that dest only."""
    options = _options(tmp_path, ())
    imports_dir = options.config.import_dir
    imports_dir.mkdir(parents=True)
    staged = imports_dir / "staged.xlsx"
    leftover = imports_dir / "leftover.xlsx"
    staged.write_bytes(b"PK\x03\x04mock")
    leftover.write_bytes(b"PK\x03\x04other")
    options = _options(tmp_path, (staged,))

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator.compute_full_pipeline_tag",
            return_value={
                "status": "ok",
                "dry_run": False,
                "total": 0,
                "tagged": 0,
                "untagged": 0,
                "coverage_pct": 0.0,
                "skipped": True,
            },
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_transfer",
            return_value={"pairs_found": 0, "pairs_linked": 0},
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_export",
            return_value={"command": "export", "transaction_count": 0, "output_files": []},
        ),
    ):
        mock_paths.return_value = _ingest_batch_summary()
        result = run_import(options)

    mock_all.assert_not_called()
    mock_paths.assert_called_once()
    ingested = mock_paths.call_args.args[0]
    assert ingested == [staged.resolve()]
    assert leftover.resolve() not in ingested
    assert result.dry_run is False
    assert result.payload["files_skipped"] == 1
    assert result.payload["files_processed"] == 0


def test_run_import_existing_dest_without_force_does_not_ingest(
    tmp_path: Path,
) -> None:
    """Skip-because-dest-exists must not ingest that dest or glob the whole dir."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = downloads / "existing.xlsx"
    source.write_bytes(b"PK\x03\x04new")

    options = _options(tmp_path, (source,))
    imports_dir = options.config.import_dir
    imports_dir.mkdir(parents=True)
    dest = imports_dir / "existing.xlsx"
    dest.write_bytes(b"PK\x03\x04old")
    leftover = imports_dir / "leftover.xlsx"
    leftover.write_bytes(b"PK\x03\x04other")

    captured: dict[str, object] = {}

    def _capture_pipeline(ctx, config, *, emit_text: bool = True, file_paths=None):
        captured["file_paths"] = file_paths
        captured["called"] = True
        return _pipeline_summary()

    dependencies = ImportDependencies(
        is_first_run=lambda _data_dir: False,
        import_xlsx_files=import_xlsx_files,
        extract_xlsx_from_zip=Mock(return_value=None),
        zip_requires_password=lambda _zip_path: False,
        run_full_pipeline=_capture_pipeline,
    )

    result = run_import_use_case(options, dependencies=dependencies)

    assert captured.get("called") is True
    assert captured.get("file_paths") == []
    assert dest.read_bytes() == b"PK\x03\x04old"
    assert result.payload["files_skipped"] == 1
    assert result.payload["files_processed"] == 0


def test_run_import_copied_file_ingests_destination_path(tmp_path: Path) -> None:
    """A newly copied workbook is ingested at its imports/ destination, not the source."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = downloads / "fresh.xlsx"
    source.write_bytes(b"PK\x03\x04mock")
    options = _options(tmp_path, (source,))
    dest = options.config.import_dir / "fresh.xlsx"

    captured: dict[str, object] = {}

    def _capture_pipeline(ctx, config, *, emit_text: bool = True, file_paths=None):
        captured["file_paths"] = list(file_paths or [])
        return _pipeline_summary()

    dependencies = ImportDependencies(
        is_first_run=lambda _data_dir: False,
        import_xlsx_files=import_xlsx_files,
        extract_xlsx_from_zip=Mock(return_value=None),
        zip_requires_password=lambda _zip_path: False,
        run_full_pipeline=_capture_pipeline,
    )

    result = run_import_use_case(options, dependencies=dependencies)

    assert captured.get("file_paths") == [dest]
    assert dest.exists()
    assert result.payload["files_processed"] == 1
    assert result.payload["files_skipped"] == 0
