"""
Gap analyzer for tagging and category analysis.

Analyzes gaps between:
- Untagged transactions (no tags assigned)
- Tagged transactions with category mismatches
- Coverage improvement simulation

This module helps users understand and prioritize rule creation.

Mismatch type/severity constants, :class:`MismatchClassification`, and the
classification helpers live in
:mod:`finjuice.pipeline.tagging.gap_mismatch` and are re-exported here so
existing callers can keep importing from this module.

:class:`GapType`, :class:`GapAnalysis`, and the analyze/sort/filter helpers
live in :mod:`finjuice.pipeline.tagging.gap_analyzer_cluster` and are
re-exported here for the same reason.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.gap_analyzer_cluster import (
    GapAnalysis,
    GapType,
    analyze_tag_category_gaps,  # noqa: F401 — re-exported for existing callers.
    filter_actionable_gaps,  # noqa: F401 — re-exported for existing callers.
    sort_mismatch_gaps,
)
from finjuice.pipeline.tagging.gap_mismatch import (
    MISMATCH_SEVERITY_ORDER,  # noqa: F401 — re-exported for existing callers.
    MISMATCH_TYPE_CATEGORY,
    MISMATCH_TYPE_CONFLICT,
    MISMATCH_TYPE_MULTI_TAG_NOISE,
    MismatchClassification,  # noqa: F401 — re-exported for existing callers.
    _category_parts,  # noqa: F401 — re-exported for existing callers.
    _mapped_categories_for_tags,  # noqa: F401 — re-exported for existing callers.
    classify_mismatch,  # noqa: F401 — re-exported for existing callers.
)

logger = logging.getLogger(__name__)


@dataclass
class CoverageSimulation:
    """Coverage improvement simulation result."""

    top_n: int
    expected_tagged: int
    expected_coverage_pct: float
    improvement_pct: float


def simulate_coverage_improvement(
    csv_base_dir: Path,
    top_n_values: Optional[list[int]] = None,
) -> list[CoverageSimulation]:
    """
    Calculate expected coverage if top N merchants get rules.

    Args:
        csv_base_dir: Base directory for CSV partitions
        top_n_values: List of top_n values to simulate (default: [5, 10, 20])

    Returns:
        List of CoverageSimulation results
    """
    if top_n_values is None:
        top_n_values = [5, 10, 20]

    df = csv_partition.get_all_transactions(csv_base_dir)
    total = len(df)

    if total == 0:
        return []

    # Count currently tagged
    tagged_df = df.filter(pl.col("tags_final").list.len() > 0)
    current_tagged = len(tagged_df)
    current_coverage = current_tagged / total * 100

    # Find untagged transactions by merchant
    untagged_df = df.filter(
        (pl.col("tags_final").list.len() == 0) | (pl.col("tags_final").is_null())
    )

    if len(untagged_df) == 0:
        return [
            CoverageSimulation(
                top_n=n,
                expected_tagged=current_tagged,
                expected_coverage_pct=current_coverage,
                improvement_pct=0.0,
            )
            for n in top_n_values
        ]

    # Group untagged by merchant
    merchant_counts = (
        untagged_df.group_by("merchant_raw")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
    )

    results = []
    for top_n in top_n_values:
        # Take top N merchants
        top_merchants = merchant_counts.head(top_n)
        potential_new_tagged = top_merchants["count"].sum()

        expected_tagged = int(current_tagged + potential_new_tagged)
        expected_coverage = expected_tagged / total * 100
        improvement = expected_coverage - current_coverage

        results.append(
            CoverageSimulation(
                top_n=top_n,
                expected_tagged=expected_tagged,
                expected_coverage_pct=expected_coverage,
                improvement_pct=improvement,
            )
        )

    return results


def format_gap_analysis_report(
    gaps: dict[GapType, list[GapAnalysis]],
    simulations: list[CoverageSimulation],
    top_n_per_category: int = 5,
) -> str:
    """
    Format gap analysis as a human-readable report.

    Args:
        gaps: Dictionary of gap types to analysis results
        simulations: Coverage simulation results
        top_n_per_category: Number of items to show per category

    Returns:
        Formatted report string
    """
    lines = [
        "📊 태깅/카테고리 Gap 분석",
        "─" * 40,
        "",
    ]

    # Critical gaps (untagged)
    critical = gaps.get(GapType.CRITICAL, [])
    critical_count = sum(g.transaction_count for g in critical)
    lines.append(f"🔴 미태깅 + 미분류 (가장 시급) - {critical_count}건")
    for i, gap in enumerate(critical[:top_n_per_category], 1):
        lines.append(
            f"   {i}. {gap.merchant} ({gap.transaction_count}건, ₩{gap.total_amount:,.0f})"
        )
        lines.append(f"      → {gap.suggested_action}")
    if len(critical) > top_n_per_category:
        lines.append(f"   ... 외 {len(critical) - top_n_per_category}개")
    lines.append("")

    # Mismatch gaps
    mismatch = sort_mismatch_gaps(
        [
            *gaps.get(GapType.MISMATCH, []),
            *gaps.get(GapType.PARTIAL, []),
        ]
    )
    mismatch_count = sum(g.transaction_count for g in mismatch)
    lines.append(f"🟡 태깅됨 + 불일치 (검토 필요) - {mismatch_count}건")
    for i, gap in enumerate(mismatch[:top_n_per_category], 1):
        mismatch_label = {
            MISMATCH_TYPE_CONFLICT: "충돌",
            MISMATCH_TYPE_CATEGORY: "카테고리 불일치",
            MISMATCH_TYPE_MULTI_TAG_NOISE: "복수 태그 노이즈",
        }.get(gap.mismatch_type or "", "불일치")
        lines.append(
            f"   {i}. [{mismatch_label}] {gap.merchant} "
            f'→ 태그 {gap.current_tags}, 카테고리 "{gap.current_category}"'
        )
    if len(mismatch) > top_n_per_category:
        lines.append(f"   ... 외 {len(mismatch) - top_n_per_category}개")
    lines.append("")

    # Complete matches
    complete = gaps.get(GapType.COMPLETE, [])
    complete_count = sum(g.transaction_count for g in complete)
    lines.append(f"🟢 완전 매칭 - {complete_count}건")
    lines.append("")

    # Coverage simulation
    if simulations:
        lines.append("📈 커버리지 개선 시뮬레이션")
        lines.append("─" * 40)
        for sim in simulations:
            lines.append(
                f"상위 {sim.top_n}개 규칙 추가 시: "
                f"{sim.expected_coverage_pct:.1f}% (+{sim.improvement_pct:.1f}%p)"
            )
        lines.append("")

    # Recommendations
    if critical:
        top_critical = critical[:3]
        merchant_names = ", ".join(g.merchant for g in top_critical)
        lines.append(f"💡 권장: {merchant_names} 규칙 먼저 추가")
        lines.append("   → finjuice rules suggest --apply --top 5")

    return "\n".join(lines)
