"""Merchant gap analysis helpers for tag/category coverage.

Owns :class:`GapType`, :class:`GapAnalysis`, and the analyze/sort/filter
helpers used to surface untagged and mismatched merchants. Coverage
simulation and report formatting stay in
:mod:`finjuice.pipeline.tagging.gap_analyzer`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.gap_mismatch import (
    MISMATCH_SEVERITY_ORDER,
    classify_mismatch,
)
from finjuice.pipeline.tagging.suggestions import get_banksalad_category


class GapType(Enum):
    """Classification of gap severity."""

    CRITICAL = "미태깅 + 미분류"  # No tags AND category is "기타"
    MISMATCH = "태깅됨 + 불일치"  # Has tags BUT category doesn't match
    PARTIAL = "부분 매칭"  # Some tags match category
    COMPLETE = "완전 매칭"  # Tags ↔ Category aligned


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
