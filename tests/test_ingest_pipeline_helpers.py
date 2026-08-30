"""Identity checks for ingest pipeline write-summary helper extraction."""

from pathlib import Path

from finjuice.pipeline.ingest import pipeline, pipeline_helpers

INGEST_DIR = Path("src/finjuice/pipeline/ingest")


def test_write_summary_helpers_live_in_helper_module() -> None:
    """Per-file and batch write summaries should not live in pipeline.py."""
    pipeline_text = (INGEST_DIR / "pipeline.py").read_text(encoding="utf-8")
    helpers_text = (INGEST_DIR / "pipeline_helpers.py").read_text(encoding="utf-8")

    assert "def preview_ingest_paths" in pipeline_text
    assert "def ingest_file" in pipeline_text
    assert "def ingest_file_detailed" in pipeline_text
    assert "def ingest_all_files" in pipeline_text
    assert "def _empty_ingest_file_summary" not in pipeline_text
    assert "def _empty_ingest_all_summary" not in pipeline_text
    assert "def _accumulate_ingest_file" not in pipeline_text
    assert "def _finalize_ingest_all_summary" not in pipeline_text
    assert "class _IngestTotals" not in pipeline_text
    assert "def _empty_ingest_file_summary" in helpers_text
    assert "def _empty_ingest_all_summary" in helpers_text
    assert "def _accumulate_ingest_file" in helpers_text
    assert "def _finalize_ingest_all_summary" in helpers_text
    assert "class _IngestTotals" in helpers_text


def test_write_summary_helpers_reexport_from_pipeline() -> None:
    """Write-summary helpers stay importable from pipeline after the split."""
    assert pipeline._IngestTotals is pipeline_helpers._IngestTotals
    assert pipeline._empty_ingest_file_summary is pipeline_helpers._empty_ingest_file_summary
    assert pipeline._empty_ingest_all_summary is pipeline_helpers._empty_ingest_all_summary
    assert pipeline._accumulate_ingest_file is pipeline_helpers._accumulate_ingest_file
    assert pipeline._finalize_ingest_all_summary is pipeline_helpers._finalize_ingest_all_summary
    assert callable(pipeline.preview_ingest_paths)
    assert callable(pipeline.preview_ingest_all_files)
    assert callable(pipeline.ingest_file)
    assert callable(pipeline.ingest_file_detailed)
    assert callable(pipeline.ingest_all_files)


def test_empty_write_summaries_keep_existing_payload_shape() -> None:
    """Empty per-file and batch payloads stay on the original keys."""
    file_summary = pipeline._empty_ingest_file_summary()
    batch_summary = pipeline._empty_ingest_all_summary()

    assert file_summary["transactions"] == {
        "inserted": 0,
        "dedup_skips": 0,
        "validation_skips": 0,
        "skipped_rows": [],
    }
    assert file_summary["asset_snapshots"] == {"inserted": 0, "dedup_skips": 0, "warnings": []}
    assert "banksalad_overview" in file_summary
    assert batch_summary == {"files": 0, "inserted": 0, "updated": 0, "failed": 0}
