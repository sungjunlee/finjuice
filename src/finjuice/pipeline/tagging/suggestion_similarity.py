"""Merchant similarity and clustering helpers for `finjuice rules suggest`.

This module owns text normalization used by similarity comparisons, spend-profile
look-alikes, and suggestion-only fuzzy merchant clusters, including truncated
card-statement names that share a specific prefix.

:mod:`finjuice.pipeline.tagging.suggestion_scoring` re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

MERCHANT_CLUSTER_REASON = "normalized_merchant_match"
TRUNCATED_MERCHANT_CLUSTER_REASON = "truncated_merchant_prefix"
MIN_TRUNCATED_PREFIX_LEN = 7


def _normalize_text(value: Any) -> str | None:
    """Return a stripped string or None for blank/null values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_merchant_for_similarity(value: Any) -> str:
    """Normalize merchant text for conservative spacing/punctuation/case comparisons."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[\W_]+", "", text.casefold())


def _merchant_similarity_score(left: Any, right: Any) -> float:
    """Return a deterministic merchant-name similarity score in the range 0..1."""
    left_key = _normalize_merchant_for_similarity(left)
    right_key = _normalize_merchant_for_similarity(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return round(SequenceMatcher(None, left_key, right_key).ratio(), 2)


def _relative_amount_difference(left: float, right: float) -> float:
    """Return the relative difference between two amounts."""
    baseline = max(abs(left), abs(right))
    if baseline == 0:
        return 0.0
    return abs(left - right) / baseline


def _find_similar_merchants(
    merchant: str,
    avg_amount: float,
    tagged_merchants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find tagged merchants with similar average spend profiles."""
    candidates: list[tuple[float, dict[str, Any]]] = []
    for candidate in tagged_merchants:
        candidate_merchant = _normalize_text(candidate.get("merchant"))
        candidate_category = _normalize_text(candidate.get("category")) or "미분류"
        candidate_avg_amount = float(candidate.get("avg_amount") or 0.0)

        if not candidate_merchant or candidate_merchant == merchant:
            continue
        if _relative_amount_difference(avg_amount, candidate_avg_amount) >= 0.5:
            continue

        candidates.append(
            (
                _relative_amount_difference(avg_amount, candidate_avg_amount),
                {
                    "merchant": candidate_merchant,
                    "category": candidate_category,
                    "avg_amount": round(candidate_avg_amount, 2),
                    "transaction_count": int(candidate.get("transaction_count") or 0),
                },
            )
        )

    candidates.sort(
        key=lambda item: (
            item[0],
            -item[1]["transaction_count"],
            item[1]["merchant"],
        )
    )
    return [candidate for _, candidate in candidates[:3]]


def _merchant_cluster_member(context: dict[str, Any]) -> dict[str, Any] | None:
    """Return the public cluster member payload for one merchant context."""
    merchant = _normalize_text(context.get("merchant"))
    if not merchant:
        return None
    return {
        "merchant": merchant,
        "transaction_count": int(context.get("transaction_count") or 0),
        "avg_amount": round(float(context.get("avg_amount") or 0.0), 2),
    }


def _empty_merchant_cluster(merchant: str) -> dict[str, Any]:
    """Return the default no-cluster payload for suggestion JSON."""
    return {
        "key": _normalize_merchant_for_similarity(merchant),
        "members": [],
        "reason": "none",
        "confidence": 0.0,
    }


def _unique_cluster_merchants(contexts: list[dict[str, Any]]) -> list[str]:
    """Return sorted unique merchant names from cluster member contexts."""
    return sorted(
        {
            str(context["merchant"])
            for context in contexts
            if _normalize_text(context.get("merchant"))
        }
    )


def _is_truncated_prefix_pair(short_key: str, long_key: str) -> bool:
    """Return whether *short_key* looks like a card-statement truncation of *long_key*.

    The prefix must be long enough that a conglomerate stem such as ``롯데쇼핑``
    or ``롯데쇼핑(주)`` does not pull unrelated banners like ``롯데마트`` into the
    same cluster.
    """
    if not short_key or not long_key or short_key == long_key:
        return False
    if len(short_key) < MIN_TRUNCATED_PREFIX_LEN:
        return False
    return long_key.startswith(short_key)


def _merge_truncated_prefix_groups(
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge normalized groups when a unique longer name continues a truncated prefix."""
    keys = list(grouped)
    parent = {key: key for key in keys}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if len(left_root) <= len(right_root):
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    for short_key in keys:
        longer_matches = [
            long_key for long_key in keys if _is_truncated_prefix_pair(short_key, long_key)
        ]
        if len(longer_matches) != 1:
            continue
        union(short_key, longer_matches[0])

    merged: dict[str, list[dict[str, Any]]] = {}
    for key, contexts in grouped.items():
        merged.setdefault(find(key), []).extend(contexts)
    return merged


def _merchant_cluster_payload(
    key: str,
    contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the public cluster payload, or None when the group is a singleton."""
    unique_merchants = _unique_cluster_merchants(contexts)
    if len(unique_merchants) < 2:
        return None

    members = [
        member
        for member in (_merchant_cluster_member(context) for context in contexts)
        if member is not None
    ]
    members.sort(
        key=lambda member: (
            -int(member["transaction_count"]),
            str(member["merchant"]),
        )
    )
    confidence = min(
        _merchant_similarity_score(left, right)
        for index, left in enumerate(unique_merchants)
        for right in unique_merchants[index + 1 :]
    )
    normalized_keys = {
        _normalize_merchant_for_similarity(merchant) for merchant in unique_merchants
    }
    reason = (
        MERCHANT_CLUSTER_REASON
        if len(normalized_keys) == 1
        else TRUNCATED_MERCHANT_CLUSTER_REASON
    )
    return {
        "key": key,
        "members": members,
        "reason": reason,
        "confidence": round(float(confidence), 2),
    }


def _build_fuzzy_merchant_clusters(
    merchant_contexts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build suggestion-only clusters for spacing variants and truncated store names."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for context in merchant_contexts:
        merchant = _normalize_text(context.get("merchant"))
        key = _normalize_merchant_for_similarity(merchant)
        if not merchant or not key:
            continue
        grouped.setdefault(key, []).append(context)

    clusters: dict[str, dict[str, Any]] = {}
    for key, contexts in _merge_truncated_prefix_groups(grouped).items():
        cluster = _merchant_cluster_payload(key, contexts)
        if cluster is None:
            continue
        for merchant in _unique_cluster_merchants(contexts):
            clusters[merchant] = cluster

    return clusters
