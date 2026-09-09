"""Scoring and candidate generation for `finjuice rules suggest`.

This module owns merchant-context assembly.

Payment-gateway classification lives in
:mod:`finjuice.pipeline.tagging.suggestion_scoring_classify` and is
re-exported here so existing callers can keep importing from this module.

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

Suggested-rule candidate payloads live in
:mod:`finjuice.pipeline.tagging.suggestion_scoring_cluster` and are re-exported
here so existing callers can keep importing from this module.

CLI report formatting and rules.yaml serialization live in
:mod:`finjuice.pipeline.tagging.suggestion_format`. Banksalad category mapping
and mapping-guide formatting live in
:mod:`finjuice.pipeline.tagging.suggestion_format_cluster` and are re-exported
through the format module. Callers should keep importing the documented public
surface from :mod:`finjuice.pipeline.tagging.suggestions`.
"""

from __future__ import annotations

import logging
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
from finjuice.pipeline.tagging.suggestion_scoring_classify import (
    PAYMENT_GATEWAY_AMBIGUOUS_REASON as PAYMENT_GATEWAY_AMBIGUOUS_REASON,
)
from finjuice.pipeline.tagging.suggestion_scoring_classify import (
    classify_merchant_kind as classify_merchant_kind,
)
from finjuice.pipeline.tagging.suggestion_scoring_classify import (
    is_auto_apply_eligible as is_auto_apply_eligible,
)
from finjuice.pipeline.tagging.suggestion_scoring_cluster import (
    RECURRING_PRIORITY_BOOST,  # noqa: F401 — re-exported for suggestions callers.
    SUGGESTED_RULE_PRIORITY,  # noqa: F401 — re-exported for suggestions callers.
    _banksalad_category_parts,  # noqa: F401 — re-exported for format callers.
    _deduplicate_rule_name,  # noqa: F401 — tests import via suggestions.
    _default_category_from_suggestion,  # noqa: F401 — re-exported for format callers.
    _default_tags_from_suggestion,  # noqa: F401 — re-exported for format callers.
    _sanitize_rule_name,  # noqa: F401 — tests import via suggestions.
    build_suggested_rule_field,
    get_suggested_rule_name,  # noqa: F401 — re-exported for existing imports.
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


def _round_ratio(value: Any) -> float:
    """Normalize ratio values for JSON-safe output."""
    if value is None:
        return 0.0
    return round(float(value), 2)


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
