"""Coverage-stat shaping helpers for `finjuice rules suggest`.

Owns typed stat readers, transfer-exclusion augmentation, and the shared
additive count payload. JSON compute stays in
:mod:`finjuice.pipeline.tagging.suggest_compute`, which re-exports these
names so existing callers can keep importing from that module. Compact
privacy projection lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_compact`. The domain error
lives in :mod:`finjuice.pipeline.tagging.suggest_compute_error`.
"""

from __future__ import annotations

from typing import Any

TRANSFER_EXCLUSION_DESCRIPTION = (
    "Only rows where is_transfer == 1 and transfer_group_id is present are excluded; "
    "unconfirmed transfer candidates remain suggestable."
)


def _stats_int(stats: dict[str, Any], key: str, fallback: int = 0) -> int:
    """Read an integer coverage stat with fallback for older test doubles."""
    return int(stats.get(key, fallback) or 0)


def _stats_float(stats: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    """Read a float coverage stat with fallback for older test doubles."""
    return float(stats.get(key, fallback) or 0.0)


def _augment_suggestion_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Add explicit transfer-exclusion fields while keeping legacy stat keys."""
    total_count = _stats_int(stats, "total_count")
    untagged_count = _stats_int(stats, "untagged_count")
    suggestable_total_count = _stats_int(stats, "suggestable_total_count", total_count)
    suggestable_untagged_count = _stats_int(
        stats,
        "suggestable_untagged_count",
        untagged_count,
    )
    transfer_excluded_count = _stats_int(
        stats,
        "transfer_excluded_count",
        max(total_count - suggestable_total_count, 0),
    )
    transfer_excluded_untagged_count = _stats_int(
        stats,
        "transfer_excluded_untagged_count",
        max(untagged_count - suggestable_untagged_count, 0),
    )
    coverage_before = _stats_float(stats, "coverage_before_pct")
    suggestable_coverage_before = _stats_float(
        stats,
        "suggestable_coverage_before_pct",
        coverage_before,
    )

    return {
        **stats,
        "total_count": total_count,
        "untagged_count": untagged_count,
        "suggestable_total_count": suggestable_total_count,
        "suggestable_untagged_count": suggestable_untagged_count,
        "transfer_excluded_count": transfer_excluded_count,
        "transfer_excluded_untagged_count": transfer_excluded_untagged_count,
        "coverage_before_pct": round(float(coverage_before), 2),
        "suggestable_coverage_before_pct": round(float(suggestable_coverage_before), 2),
    }


def _suggest_transfer_exclusions(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the transfer-exclusion explanation for `rules suggest` JSON."""
    return {
        "excluded_count": _stats_int(stats, "transfer_excluded_count"),
        "excluded_untagged_count": _stats_int(stats, "transfer_excluded_untagged_count"),
        "definition": TRANSFER_EXCLUSION_DESCRIPTION,
    }


def _rules_suggest_count_payload(stats: dict[str, Any]) -> dict[str, Any]:
    """Return the shared additive count payload for `rules suggest`."""
    return {
        "untagged_count": _stats_int(stats, "untagged_count"),
        "suggestable_untagged_count": _stats_int(stats, "suggestable_untagged_count"),
        "total_count": _stats_int(stats, "total_count"),
        "suggestable_total_count": _stats_int(stats, "suggestable_total_count"),
        "transfer_exclusions": _suggest_transfer_exclusions(stats),
        "coverage_before_pct": round(_stats_float(stats, "coverage_before_pct"), 2),
        "suggestable_coverage_before_pct": round(
            _stats_float(stats, "suggestable_coverage_before_pct"),
            2,
        ),
    }
