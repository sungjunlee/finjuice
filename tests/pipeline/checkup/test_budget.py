"""Focused tests for the budget posture collector."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from finjuice.pipeline.checkup.budget import collect_budget_posture
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions


def test_collect_budget_posture_missing_goals_is_unconfigured(tmp_path: Path) -> None:
    """A missing goals.yaml should be an explicit missing_config posture."""
    data_dir = init_data_dir(tmp_path, "missing-goals")
    summary = collect_budget_posture(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert summary.status == "missing_config"
    assert summary.actionable is True
    assert summary.goals_file_exists is False
    assert summary.summary is None
    assert summary.warning is not None


def test_collect_budget_posture_invalid_goals_is_actionable(tmp_path: Path) -> None:
    """Invalid goals.yaml should not collapse into a healthy budget posture."""
    data_dir = init_data_dir(tmp_path, "invalid-goals")
    (data_dir / "goals.yaml").write_text(
        "version: 1\nmonthly_budget: not-a-mapping\n", encoding="utf-8"
    )

    summary = collect_budget_posture(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert summary.status == "invalid"
    assert summary.actionable is True
    assert summary.goals_file_exists is True
    assert summary.warning is not None


def test_collect_budget_posture_over_budget_needs_attention(tmp_path: Path) -> None:
    """Spend above the monthly target should mark budget posture as needs_attention."""
    data_dir = init_data_dir(tmp_path, "over-budget")
    write_transactions(
        data_dir,
        "2026-01",
        [
            _tx_row(
                "2026-01-12",
                -105_000.0,
                "마트",
                category_final="식비",
                tags_final='["식비"]',
            ),
            _tx_row(
                "2026-01-15",
                -30_000.0,
                "병원",
                category_final="의료",
                tags_final='["의료"]',
            ),
        ],
    )
    (data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 100000",
                "  categories:",
                "    식비: 100000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = collect_budget_posture(Config(data_dir=data_dir), today=date(2026, 4, 18))

    assert summary.status == "needs_attention"
    assert summary.actionable is True
    assert summary.summary is not None
    assert summary.summary.actual == 135000
    assert summary.over_budget_categories == ["식비"]
    assert summary.unbudgeted_categories == ["의료"]
