"""Merchant similarity and clustering helpers for `finjuice rules suggest`.

This module owns text normalization used by similarity comparisons, spend-profile
look-alikes, suggestion-only fuzzy merchant clusters, and truncated-store
prefix merges.

:mod:`finjuice.pipeline.tagging.suggestion_scoring` re-exports the names that
existing callers import from that module.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from finjuice.pipeline.tagging.suggestion_scoring_helpers import _clean_merchant_name

MERCHANT_CLUSTER_REASON = "normalized_merchant_match"
TRUNCATED_STORE_CLUSTER_REASON = "truncated_store_prefix"
_MIN_TRUNCATION_PREFIX_LEN = 5
_KNOWN_DISTINCT_BRAND_KEYS = {
    "스타벅스",
    "starbucks",
    "이마트",
    "emart",
    "롯데마트",
    "lottemart",
    "롯데리아",
    "gs25",
    "cu",
    "세븐일레븐",
    "7eleven",
    "이마트24",
    "맥도날드",
    "mcdonalds",
    "버거킹",
    "burgerking",
}


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


def _build_fuzzy_merchant_clusters(
    merchant_contexts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build suggestion-only clusters for merchants with identical normalized forms."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for context in merchant_contexts:
        merchant = _normalize_text(context.get("merchant"))
        key = _normalize_merchant_for_similarity(merchant)
        if not merchant or not key:
            continue
        grouped.setdefault(key, []).append(context)

    clusters: dict[str, dict[str, Any]] = {}
    for key, contexts in grouped.items():
        unique_merchants = sorted(
            {
                str(context["merchant"])
                for context in contexts
                if _normalize_text(context.get("merchant"))
            }
        )
        if len(unique_merchants) < 2:
            continue

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
        cluster = {
            "key": key,
            "members": members,
            "reason": MERCHANT_CLUSTER_REASON,
            "confidence": round(float(confidence), 2),
        }
        for merchant in unique_merchants:
            clusters[merchant] = cluster

    return clusters


def _is_token_continuation(char: str) -> bool:
    """Return True when *char* continues a merchant token rather than a boundary."""
    return char.isalnum() or "가" <= char <= "힣"


def _ordered_merchant_pair(left: str, right: str) -> tuple[str, str]:
    """Return (shorter, longer) by raw length, then lexicographic name."""
    if (len(left), left) <= (len(right), right):
        return left, right
    return right, left


def _should_merge_truncated_store_names(left: str, right: str) -> bool:
    """Return True when *left*/*right* look like statement-truncated variants.

    Merge only when the shorter normalized name is a prefix of the longer one,
    the cut continues mid-token on the raw strings, the prefix is long enough,
    and the shorter name is not a known complete brand or branch-stripped form.
    """
    short, long_name = _ordered_merchant_pair(left, right)
    short_key = _normalize_merchant_for_similarity(short)
    long_key = _normalize_merchant_for_similarity(long_name)
    if (
        not short_key
        or not long_key
        or short_key == long_key
        or len(short_key) < _MIN_TRUNCATION_PREFIX_LEN
        or not long_key.startswith(short_key)
        or short_key in _KNOWN_DISTINCT_BRAND_KEYS
    ):
        return False
    cleaned_key = _normalize_merchant_for_similarity(_clean_merchant_name(long_name))
    if cleaned_key == short_key or not long_name.startswith(short):
        return False
    return _is_token_continuation(long_name[len(short)])


def _union_find_parents(count: int) -> list[int]:
    """Return the identity parent array for *count* items."""
    return list(range(count))


def _union_find_root(parents: list[int], index: int) -> int:
    """Return the disjoint-set root for *index*, compressing the path."""
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _union_find_merge(parents: list[int], left: int, right: int) -> None:
    """Join the sets containing *left* and *right*."""
    left_root = _union_find_root(parents, left)
    right_root = _union_find_root(parents, right)
    if left_root != right_root:
        parents[right_root] = left_root


def _weighted_context_ratio(contexts: list[dict[str, Any]], field: str) -> float:
    """Return a transaction-count-weighted mean for a ratio field."""
    weighted_total = 0.0
    weight = 0
    for context in contexts:
        count = int(context.get("transaction_count") or 0)
        if count <= 0:
            continue
        weighted_total += float(context.get(field) or 0.0) * count
        weight += count
    if weight == 0:
        return 0.0
    return weighted_total / weight


def _union_context_text_list(contexts: list[dict[str, Any]], field: str) -> list[str]:
    """Return sorted unique stripped strings from a list-valued context field."""
    values: list[str] = []
    for context in contexts:
        raw = context.get(field)
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            text = _normalize_text(item)
            if text and text not in values:
                values.append(text)
    values.sort()
    return values


def _context_name_variants(context: dict[str, Any], merchant: str) -> list[str]:
    """Return unique raw merchant name variants for a suggestion context."""
    raw = context.get("name_variants")
    if isinstance(raw, list):
        variants = [text for text in (_normalize_text(item) for item in raw) if text]
        if variants:
            return sorted(set(variants))
    return [merchant]


def _match_source_merchant(context: dict[str, Any], merchant: str) -> str:
    """Return the shortest raw variant, used as the conservative match pattern."""
    variants = _context_name_variants(context, merchant)
    return min(variants, key=lambda name: (len(name), name))


def _merge_truncated_store_contexts(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse prefix-related merchant contexts into one suggestion payload."""
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
    names = sorted({str(member["merchant"]) for member in members})
    canonical = max(names, key=lambda name: (len(name), name))
    primary = max(
        contexts,
        key=lambda context: (
            int(context.get("transaction_count") or 0),
            str(context.get("merchant") or ""),
        ),
    )
    total_count = sum(int(context.get("transaction_count") or 0) for context in contexts)
    total_amount = sum(float(context.get("total_amount") or 0.0) for context in contexts)
    active_months = _union_context_text_list(contexts, "active_months")
    merged = dict(primary)
    merged["merchant"] = canonical
    merged["transaction_count"] = total_count
    merged["total_amount"] = total_amount
    merged["avg_amount"] = (total_amount / total_count) if total_count else 0.0
    merged["active_months"] = active_months
    merged["is_recurring"] = bool(primary.get("is_recurring")) or len(active_months) >= 2
    merged["sample_memos"] = _union_context_text_list(contexts, "sample_memos")
    merged["weekday_pct"] = _weighted_context_ratio(contexts, "weekday_pct")
    merged["lunch_pct"] = _weighted_context_ratio(contexts, "lunch_pct")
    merged["distinct_dates"] = max(int(context.get("distinct_dates") or 0) for context in contexts)
    merged["name_variants"] = names
    merged["merchant_cluster"] = {
        "key": _normalize_merchant_for_similarity(canonical),
        "members": members,
        "reason": TRUNCATED_STORE_CLUSTER_REASON,
        "confidence": 1.0,
    }
    return merged


def _collapse_truncated_store_contexts(
    merchant_contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge statement-truncated merchant clusters into single suggestion rows."""
    indexed: list[tuple[str, dict[str, Any]]] = []
    for context in merchant_contexts:
        merchant = _normalize_text(context.get("merchant"))
        if merchant:
            indexed.append((merchant, context))
    count = len(indexed)
    if count < 2:
        return [context for _, context in indexed] or list(merchant_contexts)

    parents = _union_find_parents(count)
    for left in range(count):
        for right in range(left + 1, count):
            if _should_merge_truncated_store_names(indexed[left][0], indexed[right][0]):
                _union_find_merge(parents, left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, (_, context) in enumerate(indexed):
        grouped.setdefault(_union_find_root(parents, index), []).append(context)

    collapsed: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) == 1:
            collapsed.append(group[0])
        else:
            collapsed.append(_merge_truncated_store_contexts(group))
    collapsed.sort(
        key=lambda context: (
            -int(context.get("transaction_count") or 0),
            str(context.get("merchant") or ""),
        )
    )
    return collapsed
