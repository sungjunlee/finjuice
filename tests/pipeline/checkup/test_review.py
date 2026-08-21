"""Focused tests for the review-pressure collector."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.checkup.review import collect_review_pressure
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions


def test_collect_review_pressure_empty_without_partitions(tmp_path: Path) -> None:
    """No partitions should yield a quiet empty review posture."""
    data_dir = init_data_dir(tmp_path, "empty-review")
    summary = collect_review_pressure(Config(data_dir=data_dir), sample_limit=3)

    assert summary.status == "empty"
    assert summary.actionable is False
    assert summary.total_candidates == 0
    assert summary.month is None


def test_collect_review_pressure_flags_low_confidence_and_untagged(tmp_path: Path) -> None:
    """Latest-month review pressure should count low-confidence and untagged rows."""
    data_dir = init_data_dir(tmp_path, "review")
    write_transactions(
        data_dir,
        "2026-01",
        [
            _tx_row(
                "2026-01-20",
                -15_000.0,
                "미확인 가맹점",
                category_final="미분류",
                tags_final="[]",
                needs_review=1,
                confidence=0.42,
            ),
            _tx_row(
                "2026-01-21",
                -22_000.0,
                "태그됐지만 신뢰도 낮음",
                category_final="식비",
                tags_final='["식비"]',
                confidence=0.31,
            ),
            _tx_row(
                "2026-01-12",
                -30_000.0,
                "마트",
                category_final="식비",
                tags_final='["식비"]',
            ),
        ],
    )

    summary = collect_review_pressure(Config(data_dir=data_dir), sample_limit=3)

    assert summary.status == "needs_attention"
    assert summary.actionable is True
    assert summary.month == "2026-01"
    assert summary.total_candidates == 2
    assert summary.needs_review_count == 1
    assert summary.untagged_count == 1
    assert summary.unclassified_count == 1
    assert summary.low_confidence_count == 2
    assert [sample.merchant for sample in summary.samples] == [
        "태그됐지만 신뢰도 낮음",
        "미확인 가맹점",
    ]
