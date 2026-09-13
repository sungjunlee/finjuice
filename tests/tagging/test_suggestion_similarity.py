"""Unit tests for suggestion-only merchant clustering."""

from __future__ import annotations

from finjuice.pipeline.tagging.suggestion_similarity import (
    MERCHANT_CLUSTER_REASON,
    TRUNCATED_MERCHANT_CLUSTER_REASON,
    _build_fuzzy_merchant_clusters,
)


def _context(merchant: str, transaction_count: int, avg_amount: float = 1000.0) -> dict:
    return {
        "merchant": merchant,
        "transaction_count": transaction_count,
        "avg_amount": avg_amount,
    }


def test_truncated_prefix_clusters_same_store_and_leaves_lotte_mart_alone() -> None:
    """A truncated 프리 prefix joins the full outlet name, not 롯데마트."""
    truncated = "롯데쇼핑(주) 프리"
    full_name = "롯데쇼핑(주) 프리미엄아울렛 의왕점"
    mart = "롯데마트"
    stem = "롯데쇼핑"

    clusters = _build_fuzzy_merchant_clusters(
        [
            _context(truncated, 7),
            _context(full_name, 25),
            _context(mart, 3),
            _context(stem, 4),
        ]
    )

    assert clusters[truncated]["reason"] == TRUNCATED_MERCHANT_CLUSTER_REASON
    assert clusters[full_name] is clusters[truncated]
    members = {member["merchant"] for member in clusters[truncated]["members"]}
    assert members == {truncated, full_name}
    assert mart not in clusters
    assert stem not in clusters
    member_counts = {
        member["merchant"]: member["transaction_count"]
        for member in clusters[truncated]["members"]
    }
    assert member_counts[truncated] == 7
    assert member_counts[full_name] == 25


def test_spacing_variants_keep_normalized_merchant_match_reason() -> None:
    """Spacing-only variants still cluster without a truncation reason."""
    clusters = _build_fuzzy_merchant_clusters(
        [
            _context("스타벅스", 3),
            _context("스타 벅스", 2),
        ]
    )

    assert clusters["스타벅스"]["reason"] == MERCHANT_CLUSTER_REASON
    assert clusters["스타 벅스"] is clusters["스타벅스"]
    assert clusters["스타벅스"]["confidence"] == 1.0
