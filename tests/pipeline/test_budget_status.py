"""Budget status buckets for untracked vs over-budget categories."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.budget_status_helpers import (
    _budget_status,
    _build_budget_guidance,
    _status_row,
    _untracked_spend_is_material,
)

GUIDANCE_EXTRAS = {"filters_applied": 0, "unmatched_goal_categories": []}
BACKWARD_COMPAT_TOP_LEVEL = {
    "health",
    "actionable",
    "signals",
    "review",
    "next_steps",
}
BACKWARD_COMPAT_SIGNALS = {
    "goals_file_exists",
    "over_budget_count",
    "unbudgeted_count",
    "on_track_count",
    "under_budget_count",
    "remaining_total",
    "filters_applied",
}
BACKWARD_COMPAT_REVIEW = {
    "month",
    "target",
    "actual",
    "remaining",
    "at_risk_categories",
    "over_budget_categories",
    "unbudgeted_categories",
}
BACKWARD_COMPAT_ROW = {
    "name",
    "target",
    "actual",
    "remaining",
    "progress_pct",
    "status",
}


def _guidance(
    category_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return _build_budget_guidance(
        month="2026-04",
        goals_exists=True,
        summary=summary,
        category_rows=category_rows,
        extras=GUIDANCE_EXTRAS,
    )


def test_zero_target_row_is_untracked_not_over() -> None:
    """A category with no target is untracked, even when it has spend."""
    # Arrange / Act
    status = _budget_status(progress_pct=None, target=0, actual=4200)
    row = _status_row("편의점", 0, 4200)

    # Assert
    assert status == "untracked"
    assert row["status"] == "untracked"
    assert row["status"] != "over"
    assert row["progress_pct"] is None


def test_health_ok_when_all_budgeted_categories_are_fine() -> None:
    """Leftover untracked spend must not flip health when budgeted rows are under."""
    # Arrange
    category_rows = [
        _status_row("식비", 200_000, 80_000),
        _status_row("의료", 0, 20_000),
    ]
    summary = _status_row("Total", 300_000, 100_000)

    # Act
    guidance = _guidance(category_rows, summary)

    # Assert
    assert category_rows[1]["status"] == "untracked"
    assert guidance["health"]["status"] == "ok"
    assert guidance["health"]["reasons"] == []
    assert guidance["actionable"] is False
    assert guidance["signals"]["untracked_total"] == 20_000
    assert guidance["review"]["unbudgeted_categories"] == ["의료"]
    assert "의료" not in guidance["review"]["at_risk_categories"]


def test_health_warns_when_a_budgeted_category_is_over() -> None:
    """A real budgeted overage still drives health.warning even with untracked rows."""
    # Arrange
    category_rows = [
        _status_row("카페", 30_000, 40_000),
        _status_row("의료", 0, 4_200),
    ]
    summary = _status_row("Total", 250_000, 44_200)

    # Act
    guidance = _guidance(category_rows, summary)

    # Assert
    assert category_rows[0]["status"] == "over"
    assert category_rows[1]["status"] == "untracked"
    assert guidance["health"]["status"] == "warning"
    assert guidance["health"]["reasons"] == ["over_budget_categories"]
    assert guidance["review"]["over_budget_categories"] == ["카페"]
    assert guidance["signals"]["untracked_total"] == 4_200


def test_budget_guidance_keeps_backward_compat_json_fields() -> None:
    """Existing JSON fields stay present; untracked_total is additive."""
    # Arrange
    category_rows = [
        _status_row("식비", 100_000, 95_000),
        _status_row("의료", 0, 15_000),
    ]
    summary = _status_row("Total", 250_000, 110_000)

    # Act
    guidance = _guidance(category_rows, summary)

    # Assert
    assert BACKWARD_COMPAT_TOP_LEVEL <= set(guidance)
    assert BACKWARD_COMPAT_SIGNALS <= set(guidance["signals"])
    assert BACKWARD_COMPAT_REVIEW <= set(guidance["review"])
    assert BACKWARD_COMPAT_ROW <= set(summary)
    assert all(BACKWARD_COMPAT_ROW <= set(row) for row in category_rows)
    assert guidance["signals"]["untracked_total"] == 15_000
    assert guidance["signals"]["unbudgeted_count"] == 1


def test_untracked_spend_is_material_only_above_share() -> None:
    """The 25% cutoff treats leftover small categories as non-material."""
    # Arrange / Act / Assert
    assert _untracked_spend_is_material(20_000, 100_000) is False
    assert _untracked_spend_is_material(25_000, 100_000) is False
    assert _untracked_spend_is_material(25_001, 100_000) is True
    assert _untracked_spend_is_material(80_000, 160_000) is True
    assert _untracked_spend_is_material(4_200, 0) is False
