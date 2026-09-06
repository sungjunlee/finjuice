"""Structure tests for the ingest pipeline remaining helper-cluster split.

Import-history recording, optional archival, and the
transaction/asset/overview write-log-return path live in
``pipeline_cluster`` and must stay identity-equal when re-exported from
``pipeline``. Write-summary helpers stay in ``pipeline_helpers``. Preview
helpers stay in ``_preview``. Public ingest entry points stay in
``pipeline``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

INGEST_DIR = Path("src/finjuice/pipeline/ingest")
CLUSTER_MODULE = "finjuice.pipeline.ingest.pipeline_cluster"
PIPELINE_MODULE = "finjuice.pipeline.ingest.pipeline"
HELPERS_MODULE = "finjuice.pipeline.ingest.pipeline_helpers"

PUBLIC_ENTRY_NAMES = (
    "preview_ingest_paths",
    "preview_ingest_all_files",
    "ingest_file",
    "ingest_file_detailed",
    "ingest_all_files",
)
CLUSTER_HELPER_NAMES = (
    "_record_ingest_import",
    "_write_ingest_file_result",
)
HELPERS_NAMES = (
    "_empty_ingest_file_summary",
    "_empty_ingest_all_summary",
    "_accumulate_ingest_file",
    "_finalize_ingest_all_summary",
)


def test_pipeline_reexports_cluster_identity() -> None:
    """Write-path cluster helpers stay on pipeline as re-exports after the split."""
    pipeline = importlib.import_module(PIPELINE_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(pipeline, name) is getattr(cluster, name)

    for name in PUBLIC_ENTRY_NAMES:
        assert callable(getattr(pipeline, name))


def test_pipeline_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved write-path cluster is defined exactly once, in pipeline_cluster."""
    pipeline = importlib.import_module(PIPELINE_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_HELPER_NAMES:
        assert getattr(cluster, name).__module__ == CLUSTER_MODULE
        assert getattr(pipeline, name).__module__ == CLUSTER_MODULE

    for name in PUBLIC_ENTRY_NAMES:
        assert getattr(pipeline, name).__module__ == PIPELINE_MODULE


def test_cluster_lives_in_cluster_module() -> None:
    """Single-file write-path glue should not live in the public ingest module."""
    pipeline_text = (INGEST_DIR / "pipeline.py").read_text(encoding="utf-8")
    cluster_text = (INGEST_DIR / "pipeline_cluster.py").read_text(encoding="utf-8")
    helpers_text = (INGEST_DIR / "pipeline_helpers.py").read_text(encoding="utf-8")
    preview_text = (INGEST_DIR / "_preview.py").read_text(encoding="utf-8")

    for name in PUBLIC_ENTRY_NAMES:
        assert f"def {name}" in pipeline_text
        assert f"def {name}" not in cluster_text

    for name in CLUSTER_HELPER_NAMES:
        assert f"def {name}" not in pipeline_text
        assert f"def {name}" in cluster_text
        assert name in pipeline_text

    for name in HELPERS_NAMES:
        assert f"def {name}" in helpers_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" not in pipeline_text

    assert "def _preview_ingest_path" in preview_text
    assert "def _preview_ingest_path" not in cluster_text
    assert "def _preview_ingest_path" not in pipeline_text


def test_record_ingest_import_returns_file_id_without_archive(tmp_path: Path) -> None:
    """Import recording keeps issuing a file_id and skips archival by default."""
    cluster = importlib.import_module(CLUSTER_MODULE)

    source = tmp_path / "imports" / "sample.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PK")
    csv_base_dir = tmp_path / "data" / "transactions"
    csv_base_dir.mkdir(parents=True)

    file_id = cluster._record_ingest_import(
        source,
        csv_base_dir,
        archive=False,
        source_rows=3,
        file_mtime="2026-09-06T00:00:00",
    )

    history = tmp_path / "data" / "metadata" / "import_history.csv"
    assert isinstance(file_id, str)
    assert file_id
    assert history.is_file()
    assert not (tmp_path / "data" / "metadata" / "archives").exists()

    again = cluster._record_ingest_import(
        source,
        csv_base_dir,
        archive=False,
        source_rows=3,
        file_mtime="2026-09-06T00:00:00",
    )
    assert again == file_id
