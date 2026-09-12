"""Tests for targeted ingest in the shared full-pipeline orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import (
    FullPipelineOptions,
    compute_full_pipeline_ingest,
    run_full_pipeline_orchestrator,
)

_INGEST_SUMMARY = {
    "files": 1,
    "inserted": 2,
    "updated": 0,
    "failed": 0,
    "failed_files": [],
}


def _config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.import_dir = tmp_path / "imports"
    config.csv_base_dir = tmp_path / "transactions"
    config.data_dir = tmp_path
    config.import_dir.mkdir()
    config.csv_base_dir.mkdir()
    return config


def test_compute_full_pipeline_ingest_uses_ingest_paths_for_explicit_files(
    tmp_path: Path,
) -> None:
    """Explicit file_paths should ingest those workbooks, not glob imports/."""
    config = _config(tmp_path)
    target = config.import_dir / "target.xlsx"
    extra = config.import_dir / "other.xlsx"
    target.write_bytes(b"PK")
    extra.write_bytes(b"PK")

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
    ):
        mock_paths.return_value = _INGEST_SUMMARY
        result = compute_full_pipeline_ingest(config, file_paths=[target])

    mock_paths.assert_called_once_with([target], config.csv_base_dir, archive=False)
    mock_all.assert_not_called()
    assert result["summary"]["files_processed"] == 1
    assert result["summary"]["new_transactions"] == 2


def test_compute_full_pipeline_ingest_empty_file_paths_does_not_glob_all(
    tmp_path: Path,
) -> None:
    """An empty explicit list means ingest nothing, not the whole imports/ dir."""
    config = _config(tmp_path)
    (config.import_dir / "leftover.xlsx").write_bytes(b"PK")

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
    ):
        mock_paths.return_value = {
            "files": 0,
            "inserted": 0,
            "updated": 0,
            "failed": 0,
        }
        result = compute_full_pipeline_ingest(config, file_paths=[])

    mock_paths.assert_called_once_with([], config.csv_base_dir, archive=False)
    mock_all.assert_not_called()
    assert result["summary"]["files_processed"] == 0


def test_compute_full_pipeline_ingest_without_file_paths_uses_ingest_all_files(
    tmp_path: Path,
) -> None:
    """Refresh / default ingest still processes every workbook in imports/."""
    config = _config(tmp_path)

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
    ):
        mock_all.return_value = _INGEST_SUMMARY
        result = compute_full_pipeline_ingest(config)

    mock_all.assert_called_once_with(config.import_dir, config.csv_base_dir, archive=False)
    mock_paths.assert_not_called()
    assert result["summary"]["files_processed"] == 1


def test_orchestrator_default_uses_ingest_all_files(tmp_path: Path) -> None:
    """run_full_pipeline_orchestrator without file_paths keeps glob-all ingest."""
    config = _config(tmp_path)
    ctx = MagicMock()

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator.compute_full_pipeline_tag",
            return_value={"status": "ok", "skipped": True},
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_transfer",
            return_value={"pairs_found": 0, "pairs_linked": 0},
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_export",
            return_value={"command": "export", "output_files": []},
        ),
    ):
        mock_all.return_value = _INGEST_SUMMARY
        run_full_pipeline_orchestrator(ctx, config, FullPipelineOptions(command_name="refresh"))

    mock_all.assert_called_once_with(config.import_dir, config.csv_base_dir, archive=False)
    mock_paths.assert_not_called()


def test_orchestrator_with_file_paths_uses_ingest_paths(tmp_path: Path) -> None:
    """Orchestrator file_paths should reach ingest_paths, not ingest_all_files."""
    config = _config(tmp_path)
    ctx = MagicMock()
    target = config.import_dir / "only.xlsx"
    target.write_bytes(b"PK")

    with (
        patch("finjuice.pipeline.ingest.pipeline.ingest_paths") as mock_paths,
        patch("finjuice.pipeline.ingest.pipeline.ingest_all_files") as mock_all,
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator.compute_full_pipeline_tag",
            return_value={"status": "ok", "skipped": True},
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_transfer",
            return_value={"pairs_found": 0, "pairs_linked": 0},
        ),
        patch(
            "finjuice.pipeline.cli.commands.full_pipeline_orchestrator."
            "compute_full_pipeline_export",
            return_value={"command": "export", "output_files": []},
        ),
    ):
        mock_paths.return_value = _INGEST_SUMMARY
        run_full_pipeline_orchestrator(
            ctx,
            config,
            FullPipelineOptions(command_name="import", file_paths=[target]),
        )

    mock_paths.assert_called_once_with([target], config.csv_base_dir, archive=False)
    mock_all.assert_not_called()
