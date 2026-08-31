"""Scoring and candidate generation for `finjuice rules suggest`.

This module owns payment-gateway classification, suggested-rule candidate
payloads, and merchant-context assembly.

Match-pattern generation lives in
:mod:`finjuice.pipeline.tagging.suggestion_scoring_helpers` and is re-exported
here so existing callers can keep importing from this module.

Existing-rule loading and duplicate-coverage checks live in
:mod:`finjuice.pipeline.tagging.suggestion_existing_rules` and are re-exported
here so existing callers can keep importing from this module.

Merchant-context queries and coverage stats live in
:mod:`finjuice.pipeline.tagging.suggestion_queries` and are re-exported here
so existing callers can keep importing from this module.

Merchant similarity and clustering live in
:mod:`finjuice.pipeline.tagging.suggestion_similarity` and are re-exported here
so existing callers can keep importing from this module.

CLI report formatting, rules.yaml serialization, and Banksalad mapping guides
live in :mod:`finjuice.pipeline.tagging.suggestion_format`. Callers should keep
importing the documented public surface from
:mod:`finjuice.pipeline.tagging.suggestions`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from finjuice.pipeline.tagging.suggestion_existing_rules import (
    _load_existing_patterns,
    _load_existing_rule_names,
    _should_skip_existing_rule,
)
from finjuice.pipeline.tagging.suggestion_queries import (
    _merchant_context_query,
    _normalize_suggest_data_dir,
    _similar_merchants_query,
    get_suggestion_coverage_stats,  # noqa: F401 — re-exported for suggestions callers.
)
from finjuice.pipeline.tagging.suggestion_scoring_helpers import (
    _clean_merchant_name,  # noqa: F401 — re-exported for existing imports.
    _escape_regex_special_chars,  # noqa: F401 — tests import via suggestions.
    _generate_match_pattern,
)
from finjuice.pipeline.tagging.suggestion_similarity import (
    MERCHANT_CLUSTER_REASON,  # noqa: F401 — re-exported for suggestions callers.
    _build_fuzzy_merchant_clusters,
    _empty_merchant_cluster,
    _find_similar_merchants,
    _merchant_similarity_score,  # noqa: F401 — tests import via suggestions.
    _normalize_merchant_for_similarity,  # noqa: F401 — tests import via suggestions.
    _normalize_text,
)

logger = logging.getLogger(__name__)
SUGGESTED_RULE_PRIORITY = 80
PAYMENT_GATEWAY_AMBIGUOUS_REASON = "payment_gateway"
RECURRING_PRIORITY_BOOST = 5

_KNOWN_PAYMENT_GATEWAY_NORMALIZED = {
    "KGINICIS",
    "이니시스",
    "케이지이니시스",
    "NHNKCP",
    "KCP",
    "엔에이치엔케이씨피",
    "토스페이먼츠",
    "TOSSPAYMENTS",
    "나이스페이먼츠",
    "NICEPAYMENTS",
    "KICC",
    "한국정보통신",
    "ALIPAY",
    "ALIPAYCONNECT",
    "ANOMALY",
}

_PAYMENT_GATEWAY_PREFIXES = (
    "PAYPAL*",
    "PAYPAL *",
    "STRIPE*",
    "STRIPE *",
)


def _normalize_text_list(value: Any) -> list[str]:
    """Normalize DuckDB LIST values into a de-duplicated string list."""
    if value is None:
        return []
    if not isinstance(value, list):
        normalized = _normalize_text(value)
        return [normalized] if normalized else []

    values: list[str] = []
    for item in value:
        normalized = _normalize_text(item)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _normalize_payment_gateway_key(value: Any) -> str:
    """Normalize merchant text for conservative known-PG classification."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[^0-9A-Z가-힣]+", "", text.upper())


def classify_merchant_kind(merchant: Any) -> dict[str, str | None]:
    """Classify merchants that are known payment intermediaries.

    The detector is intentionally conservative. It marks well-known processor
    names and processor-style prefixes, but avoids broad substring matches so
    ordinary merchants with similar text remain eligible for normal curation.
    """
    text = _normalize_text(merchant) or ""
    key = _normalize_payment_gateway_key(text)
    upper_text = text.upper()
    is_gateway = key in _KNOWN_PAYMENT_GATEWAY_NORMALIZED or any(
        upper_text.startswith(prefix) for prefix in _PAYMENT_GATEWAY_PREFIXES
    )
    if not is_gateway:
        return {
            "merchant_kind": "merchant",
            "ambiguous_reason": None,
            "default_action": "create_rule",
        }
    return {
        "merchant_kind": "payment_gateway",
        "ambiguous_reason": PAYMENT_GATEWAY_AMBIGUOUS_REASON,
        "default_action": "skip_rule",
    }


def is_auto_apply_eligible(suggestion: dict[str, Any]) -> bool:
    """Return whether a suggestion is safe for headless rule auto-apply."""
    return suggestion.get("default_action") != "skip_rule"


def _round_ratio(value: Any) -> float:
    """Normalize ratio values for JSON-safe output."""
    if value is None:
        return 0.0
    return round(float(value), 2)


def _banksalad_category_parts(
    suggestion: dict[str, Any],
) -> tuple[str, str]:
    """Return normalized (major, minor) Banksalad category parts."""
    category = suggestion.get("banksalad_category") or {}
    major = _normalize_text(category.get("major")) or ""
    minor = _normalize_text(category.get("minor")) or ""
    return major, minor


def _default_category_from_suggestion(suggestion: dict[str, Any]) -> str:
    """Return the category value used when auto-applying a suggestion."""
    major, minor = _banksalad_category_parts(suggestion)
    return minor or major


def _default_tags_from_suggestion(suggestion: dict[str, Any]) -> list[str]:
    """Return raw Banksalad categories as tags for auto-applied rules."""
    major, minor = _banksalad_category_parts(suggestion)
    tags: list[str] = []
    for candidate in [minor, major]:
        if candidate and candidate not in tags:
            tags.append(candidate)
    return tags or ["미분류"]


def _deduplicate_rule_name(base_name: str, existing_names: set[str]) -> str:
    """Add a numeric suffix if *base_name* already exists."""
    if base_name not in existing_names:
        return base_name
    for seq in range(2, 100):
        candidate = f"{base_name}_{seq}"
        if candidate not in existing_names:
            return candidate
    return f"{base_name}_99"


def _sanitize_rule_name(merchant: str) -> str:
    """
    Sanitize merchant name for use as a rule name.

    Args:
        merchant: Raw merchant name

    Returns:
        Sanitized name suitable for YAML rule identifier
    """
    # Convert to lowercase and replace non-alphanumeric (including Korean) with underscore
    name_base = re.sub(r"[^a-zA-Z0-9가-힣]", "_", merchant.lower())
    # Collapse multiple underscores
    name_base = re.sub(r"_+", "_", name_base).strip("_")
    # Limit length
    return name_base[:30] if name_base else "unknown"


def get_suggested_rule_name(merchant: str) -> str:
    """Build the persisted rule name for a suggestion merchant."""
    return f"suggested_{_sanitize_rule_name(merchant)}"


def build_suggested_rule_field(
    suggestion: dict[str, Any],
    existing_names: set[str],
) -> dict[str, Any]:
    """Build a compact ``suggested_rule`` dict for JSON output.

    The returned dict is directly usable as ``rules add`` arguments.
    """
    merchant = str(suggestion["merchant"])
    base_name = get_suggested_rule_name(merchant)
    name = _deduplicate_rule_name(base_name, existing_names)

    category = _default_category_from_suggestion(suggestion)
    tags = _default_tags_from_suggestion(suggestion)
    priority = SUGGESTED_RULE_PRIORITY
    if suggestion.get("is_recurring"):
        priority += RECURRING_PRIORITY_BOOST

    rule: dict[str, Any] = {
        "name": name,
        "match": str(suggestion["pattern"]),
        "category": category or "미분류",
        "tags": tags,
        "priority": priority,
    }
    return rule


def generate_merchant_context(
    data_dir: Path,
    rules_file: Optional[Path] = None,
    top_n: int = 10,
    min_count: int = 2,
    file_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generate rich DuckDB-backed merchant context for untagged transactions."""
    from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics

    normalized_data_dir = _normalize_suggest_data_dir(data_dir)
    existing_patterns = _load_existing_patterns(rules_file)
    existing_names = _load_existing_rule_names(rules_file)
    # Track names assigned during this batch to prevent collisions
    used_names: set[str] = set(existing_names)
    query_limit = max(top_n * 20, top_n)

    try:
        with DuckDBAnalytics(normalized_data_dir) as analytics:
            params = (
                [file_id, min_count, query_limit]
                if file_id is not None
                else [min_count, query_limit]
            )
            merchant_contexts = (
                analytics.conn.execute(
                    _merchant_context_query(file_id),
                    params,
                )
                .pl()
                .to_dicts()
            )
            tagged_params = [file_id] if file_id is not None else []
            tagged_merchants = (
                analytics.conn.execute(_similar_merchants_query(file_id), tagged_params)
                .pl()
                .to_dicts()
            )
    except FileNotFoundError:
        logger.info("No transaction data found for merchant context generation")
        return []

    merchant_clusters = _build_fuzzy_merchant_clusters(merchant_contexts)
    suggestions: list[dict[str, Any]] = []
    for context in merchant_contexts:
        merchant = _normalize_text(context.get("merchant"))
        if not merchant:
            continue

        match_pattern = _generate_match_pattern(merchant)
        if _should_skip_existing_rule(merchant, match_pattern, existing_patterns):
            continue

        avg_amount = float(context.get("avg_amount") or 0.0)
        suggestion: dict[str, Any] = {
            "merchant": merchant,
            "transaction_count": int(context.get("transaction_count") or 0),
            "total_amount": round(float(context.get("total_amount") or 0.0), 2),
            "avg_amount": round(avg_amount, 2),
            "amount_stddev": round(float(context.get("amount_stddev") or 0.0), 2),
            "active_months": sorted(_normalize_text_list(context.get("active_months"))),
            "is_recurring": bool(context.get("is_recurring")),
            "banksalad_category": {
                "major": _normalize_text(context.get("major_raw")),
                "minor": _normalize_text(context.get("minor_raw")),
            },
            "payment_method": _normalize_text(context.get("payment_method")) or "",
            "time_patterns": {
                "weekday_pct": _round_ratio(context.get("weekday_pct")),
                "lunch_pct": _round_ratio(context.get("lunch_pct")),
            },
            "similar_merchants": _find_similar_merchants(
                merchant,
                avg_amount,
                tagged_merchants,
            ),
            "merchant_cluster": merchant_clusters.get(merchant, _empty_merchant_cluster(merchant)),
            "pattern": match_pattern,
            "sample_memos": _normalize_text_list(context.get("sample_memos"))[:3],
        }
        suggestion.update(classify_merchant_kind(merchant))
        suggestion["auto_apply_eligible"] = is_auto_apply_eligible(suggestion)
        rule_field = build_suggested_rule_field(suggestion, used_names)
        used_names.add(rule_field["name"])
        suggestion["suggested_rule"] = rule_field
        suggestions.append(suggestion)

        if len(suggestions) >= top_n:
            break

    return suggestions
