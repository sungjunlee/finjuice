"""Focused tests for the obligation-confirmation collector."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.checkup.obligations import collect_obligation_confirmation
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import (
    _tx_row,
    init_data_dir,
    month_labels,
    write_transactions,
)


def test_collect_obligation_confirmation_empty_without_partitions(tmp_path: Path) -> None:
    """No transactions should yield a quiet empty obligation posture."""
    data_dir = init_data_dir(tmp_path, "empty-obligations")
    summary = collect_obligation_confirmation(Config(data_dir=data_dir))

    assert summary.status == "empty"
    assert summary.actionable is False
    assert summary.candidate_count == 0
    assert summary.threshold_monthly_krw == 300_000


def test_collect_obligation_confirmation_surfaces_large_monthly_outflow(
    tmp_path: Path,
) -> None:
    """A large consecutive monthly outflow should need confirmation."""
    data_dir = init_data_dir(tmp_path, "obligation-candidate")
    months = month_labels(2025, 4, 8)
    for month in months:
        write_transactions(
            data_dir,
            month,
            [
                _tx_row(
                    f"{month}-05",
                    -450_000.0,
                    "주담대 1234-5678",
                    category_final="대출",
                    tags_final='["대출"]',
                )
            ],
        )

    summary = collect_obligation_confirmation(Config(data_dir=data_dir))

    assert summary.status == "needs_confirmation"
    assert summary.actionable is True
    assert summary.candidate_count == 1
    candidate = summary.candidates[0]
    assert candidate.label == "주담대 #"
    assert candidate.average_monthly_amount == 450_000
    assert "1234" not in candidate.label
