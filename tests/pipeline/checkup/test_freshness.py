"""Focused tests for the pipeline freshness collector."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from finjuice.pipeline.checkup.freshness import collect_pipeline_freshness
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions

_FIXTURE_XLSX = Path(__file__).resolve().parents[2] / "fixtures" / "sample_banksalad.xlsx"


def test_collect_pipeline_freshness_empty_state_is_actionable(tmp_path: Path) -> None:
    """Missing partitions should be an explicit empty posture, not a healthy one."""
    data_dir = init_data_dir(tmp_path, "empty")
    summary = collect_pipeline_freshness(
        Config(data_dir=data_dir),
        today=date(2026, 4, 18),
        stale_after_days=35,
    )

    assert summary.status == "empty"
    assert summary.actionable is True
    assert summary.pending_import_status == "clear"
    assert summary.warning is not None


def test_collect_pipeline_freshness_pending_imports_are_actionable(tmp_path: Path) -> None:
    """Staged imports should surface as pending even when partitions exist."""
    data_dir = init_data_dir(tmp_path, "pending")
    write_transactions(
        data_dir,
        "2026-04",
        [
            _tx_row(
                "2026-04-12",
                -30_000.0,
                "카페",
                category_final="카페",
                tags_final='["카페"]',
            )
        ],
    )
    shutil.copy(_FIXTURE_XLSX, data_dir / "imports" / "staged.xlsx")

    summary = collect_pipeline_freshness(
        Config(data_dir=data_dir),
        today=date(2026, 4, 18),
        stale_after_days=35,
    )

    assert summary.status == "pending_imports"
    assert summary.actionable is True
    assert summary.pending_import_files == 1
    assert summary.failed_import_files == 0


def test_collect_pipeline_freshness_failed_preview_is_not_refreshable(tmp_path: Path) -> None:
    """Preview failures must not be counted as pending refreshable imports."""
    data_dir = init_data_dir(tmp_path, "failed")
    (data_dir / "imports" / "broken.xlsx").write_text("not-a-valid-xlsx", encoding="utf-8")

    summary = collect_pipeline_freshness(
        Config(data_dir=data_dir),
        today=date(2026, 4, 18),
        stale_after_days=35,
    )

    assert summary.status == "import_failures"
    assert summary.actionable is True
    assert summary.pending_import_files == 0
    assert summary.failed_import_files == 1


def test_collect_pipeline_freshness_stale_after_threshold(tmp_path: Path) -> None:
    """Days since latest above the threshold should mark the pipeline stale."""
    data_dir = init_data_dir(tmp_path, "stale")
    write_transactions(
        data_dir,
        "2026-01",
        [
            _tx_row(
                "2026-01-23",
                -9_000.0,
                "카페",
                category_final="카페",
                tags_final='["카페"]',
            )
        ],
    )

    summary = collect_pipeline_freshness(
        Config(data_dir=data_dir),
        today=date(2026, 4, 18),
        stale_after_days=35,
    )

    assert summary.status == "stale"
    assert summary.actionable is True
    assert summary.days_since_latest == 85
