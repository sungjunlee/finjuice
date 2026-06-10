"""
Gap analyzer for tagging and category analysis.

Analyzes gaps between:
- Untagged transactions (no tags assigned)
- Tagged transactions with category mismatches
- Coverage improvement simulation

This module helps users understand and prioritize rule creation.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.suggestions import get_banksalad_category

logger = logging.getLogger(__name__)


class GapType(Enum):
    """Classification of gap severity."""

    CRITICAL = "미태깅 + 미분류"  # No tags AND category is "기타"
    MISMATCH = "태깅됨 + 불일치"  # Has tags BUT category doesn't match
    PARTIAL = "부분 매칭"  # Some tags match category
    COMPLETE = "완전 매칭"  # Tags ↔ Category aligned


MISMATCH_TYPE_CONFLICT = "conflict"
MISMATCH_TYPE_CATEGORY = "category_mismatch"
MISMATCH_TYPE_MULTI_TAG_NOISE = "multi_tag_noise"
MISMATCH_SEVERITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "none": 3,
}


@dataclass
class GapAnalysis:
    """Analysis result for a merchant/pattern gap."""

    gap_type: GapType
    merchant: str
    transaction_count: int
    total_amount: float
    current_tags: list[str]
    current_category: str  # Banksalad raw category (major:minor)
    suggested_action: str
    expected_category: str | None = None
    mismatch_type: str | None = None
    mismatch_severity: str = "none"
    actionable: bool = True


@dataclass
class CoverageSimulation:
    """Coverage improvement simulation result."""

    top_n: int
    expected_tagged: int
    expected_coverage_pct: float
    improvement_pct: float


@dataclass(frozen=True)
class MismatchClassification:
    """Actionability metadata for tagged category mismatches."""

    mismatch_type: str
    mismatch_severity: str
    actionable: bool


def _category_parts(category: str) -> tuple[str, str]:
    """Split a major:minor category string into normalized parts."""
    major, separator, minor = (category or "").partition(":")
    if not separator:
        return major or "기타", ""
    return major or "기타", minor or ""


def _mapped_categories_for_tags(tags: list[str]) -> list[str]:
    """Return unique non-fallback Banksalad categories for individual tags."""
    categories: list[str] = []
    for tag in tags:
        category = get_banksalad_category([tag])
        if category == "기타:기타":
            continue
        if category not in categories:
            categories.append(category)
    return categories


def classify_mismatch(
    tags: list[str],
    raw_category: str,
    expected_category: str,
) -> MismatchClassification:
    """Classify mismatch severity without mutating transactions or rules."""
    mapped_categories = _mapped_categories_for_tags(tags)
    if len(tags) > 1 and raw_category in mapped_categories and raw_category != expected_category:
        return MismatchClassification(
            mismatch_type=MISMATCH_TYPE_MULTI_TAG_NOISE,
            mismatch_severity="low",
            actionable=False,
        )

    raw_major, _raw_minor = _category_parts(raw_category)
    expected_major, _expected_minor = _category_parts(expected_category)
    if raw_major != expected_major and raw_major != "기타" and expected_major != "기타":
        return MismatchClassification(
            mismatch_type=MISMATCH_TYPE_CONFLICT,
            mismatch_severity="high",
            actionable=True,
        )

    return MismatchClassification(
        mismatch_type=MISMATCH_TYPE_CATEGORY,
        mismatch_severity="medium",
        actionable=True,
    )


def sort_mismatch_gaps(gaps: list[GapAnalysis]) -> list[GapAnalysis]:
    """Sort mismatches by severity, then impact, then merchant name."""
    return sorted(
        gaps,
        key=lambda gap: (
            MISMATCH_SEVERITY_ORDER.get(gap.mismatch_severity, 99),
            -gap.transaction_count,
            gap.merchant,
        ),
    )


def filter_actionable_gaps(
    gaps: dict[GapType, list[GapAnalysis]],
) -> dict[GapType, list[GapAnalysis]]:
    """Return a copy of gaps with low-signal non-actionable mismatches removed."""
    return {
        gap_type: [
            gap
            for gap in analyses
            if gap_type not in {GapType.MISMATCH, GapType.PARTIAL} or gap.actionable
        ]
        for gap_type, analyses in gaps.items()
    }


def analyze_tag_category_gaps(
    csv_base_dir: Path,
) -> dict[GapType, list[GapAnalysis]]:
    """
    Analyze gaps between tags and Banksalad categories.

    Args:
        csv_base_dir: Base directory for CSV partitions

    Returns:
        Dictionary mapping GapType to list of GapAnalysis
    """
    df = csv_partition.get_all_transactions(csv_base_dir)

    if len(df) == 0:
        return {gap_type: [] for gap_type in GapType}

    results: dict[GapType, list[GapAnalysis]] = {gap_type: [] for gap_type in GapType}

    # Group by merchant for analysis
    merchant_stats = (
        df.group_by("merchant_raw")
        .agg(
            [
                pl.len().alias("count"),
                pl.col("amount").sum().alias("total_amount"),
                # Get most common tags_final (first non-empty or empty list)
                pl.col("tags_final").first().alias("tags_sample"),
                # Get most common major_raw category
                pl.col("major_raw").first().alias("major_raw"),
                pl.col("minor_raw").first().alias("minor_raw"),
            ]
        )
        .sort("count", descending=True)
    )

    for row in merchant_stats.iter_rows(named=True):
        merchant = row["merchant_raw"] or ""
        if not merchant:
            continue

        count = row["count"]
        total = abs(row["total_amount"])

        # Parse tags
        tags_sample = row["tags_sample"]
        tags = tags_sample if isinstance(tags_sample, list) else []

        # Build raw category string
        major = row["major_raw"] or "기타"
        minor = row["minor_raw"] or "기타"
        raw_category = f"{major}:{minor}"

        # Determine gap type
        expected_category: str | None = None
        mismatch_type: str | None = None
        mismatch_severity = "none"
        actionable = True
        if not tags:
            # No tags - critical gap
            gap_type = GapType.CRITICAL
            suggested_action = "규칙 추가 필요: finjuice rules suggest 실행"
        else:
            # Has tags - check if they match category
            expected_category = get_banksalad_category(tags)
            if raw_category == expected_category:
                gap_type = GapType.COMPLETE
                suggested_action = "매칭됨 - 조치 불필요"
            else:
                classification = classify_mismatch(tags, raw_category, expected_category)
                mismatch_type = classification.mismatch_type
                mismatch_severity = classification.mismatch_severity
                actionable = classification.actionable
                if "기타" in raw_category:
                    gap_type = GapType.MISMATCH
                    suggested_action = f"뱅크샐러드 앱에서 카테고리를 {expected_category}로 변경"
                elif not actionable:
                    gap_type = GapType.PARTIAL
                    suggested_action = (
                        "복수 태그 순서로 인한 저신호 불일치 - 필요 시 태그 순서 검토"
                    )
                else:
                    gap_type = GapType.PARTIAL
                    suggested_action = f"태그 검토: 현재 {tags} → 카테고리 {raw_category}"

        analysis = GapAnalysis(
            gap_type=gap_type,
            merchant=merchant,
            transaction_count=count,
            total_amount=total,
            current_tags=tags,
            current_category=raw_category,
            suggested_action=suggested_action,
            expected_category=expected_category,
            mismatch_type=mismatch_type,
            mismatch_severity=mismatch_severity,
            actionable=actionable,
        )
        results[gap_type].append(analysis)

    return results


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
