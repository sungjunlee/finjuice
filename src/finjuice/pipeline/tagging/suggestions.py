"""DuckDB-backed merchant context provider for `finjuice rules suggest`.

The suggest command now produces rich merchant context instead of low-quality
tag guesses. AI agents or users can use this context to decide on categories
and tags, while `--apply --yes` still builds valid rules from the raw
Banksalad categories already present in the data.
"""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from finjuice.pipeline.filters import exclude_transfers_sql
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import append_rule, load_rules

logger = logging.getLogger(__name__)
SUGGESTED_RULE_PRIORITY = 80
MERCHANT_CLUSTER_REASON = "normalized_merchant_match"
PAYMENT_GATEWAY_AMBIGUOUS_REASON = "payment_gateway"

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


def _normalize_suggest_data_dir(path: Path) -> Path:
    """Normalize either a data directory or `transactions/` path to the data dir."""
    candidate = Path(path)
    if candidate.name == "transactions":
        return candidate.parent
    return candidate


def _normalize_text(value: Any) -> str | None:
    """Return a stripped string or None for blank/null values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _normalize_merchant_for_similarity(value: Any) -> str:
    """Normalize merchant text for conservative spacing/punctuation/case comparisons."""
    text = _normalize_text(value)
    if not text:
        return ""
    return re.sub(r"[\W_]+", "", text.casefold())


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


def _merchant_similarity_score(left: Any, right: Any) -> float:
    """Return a deterministic merchant-name similarity score in the range 0..1."""
    left_key = _normalize_merchant_for_similarity(left)
    right_key = _normalize_merchant_for_similarity(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return round(SequenceMatcher(None, left_key, right_key).ratio(), 2)


def _round_ratio(value: Any) -> float:
    """Normalize ratio values for JSON-safe output."""
    if value is None:
        return 0.0
    return round(float(value), 2)


def _relative_amount_difference(left: float, right: float) -> float:
    """Return the relative difference between two amounts."""
    baseline = max(abs(left), abs(right))
    if baseline == 0:
        return 0.0
    return abs(left - right) / baseline


def _load_existing_patterns(rules_file: Optional[Path]) -> set[str]:
    """Load normalized rule match segments to avoid duplicate suggestions."""
    if not rules_file or not rules_file.exists():
        return set()

    patterns: set[str] = set()
    for rule in load_rules(rules_file):
        for segment in rule.match.split("|"):
            normalized = segment.strip().lower()
            if normalized:
                patterns.add(normalized)
    return patterns


def _load_existing_rule_names(rules_file: Optional[Path]) -> set[str]:
    """Load existing rule names to detect conflicts."""
    if not rules_file or not rules_file.exists():
        return set()
    return {rule.name for rule in load_rules(rules_file)}


def _should_skip_existing_rule(
    merchant: str,
    match_pattern: str,
    existing_patterns: set[str],
) -> bool:
    """Return True when a merchant already appears covered by an existing rule."""
    merchant_lower = merchant.lower()
    pattern_lower = match_pattern.lower()

    if merchant_lower in existing_patterns or pattern_lower in existing_patterns:
        return True

    return any(
        existing in merchant_lower or existing in pattern_lower or pattern_lower in existing
        for existing in existing_patterns
    )


def _clean_merchant_name(name: str) -> str:
    """
    Clean merchant name for pattern matching.

    Removes common suffixes like store numbers, branches, etc.
    """
    if not name:
        return ""

    # Remove common Korean branch suffixes
    # e.g., "스타벅스 강남역점" -> "스타벅스"
    # e.g., "GS25 역삼1호점" -> "GS25"
    patterns_to_remove = [
        r"\s+\d+호점$",  # 1호점, 2호점
        r"\s+[가-힣]+점$",  # 강남점, 역삼점
        r"\s+[가-힣]+역점$",  # 강남역점
        r"\s+\d+번출구점$",  # 1번출구점
        r"\s*\([^)]+\)$",  # (주), (유) at end
        r"\s+지점$",
        r"\s+본점$",
    ]

    cleaned = name
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, "", cleaned)

    return cleaned.strip()


def _escape_regex_special_chars(text: str) -> str:
    """
    Escape regex special characters for safe pattern matching.

    Issue #154: Handles parentheses and other special chars in merchant names
    like "(주)이마트", "지에스(GS)25".

    Args:
        text: Raw text that may contain regex special characters

    Returns:
        Text with special characters escaped
    """
    # Characters that have special meaning in regex: ( ) [ ] { } . * + ? ^ $ \ |
    # Note: We preserve | for OR patterns when joining cleaned and original
    return re.sub(r"([()[\]{}.*+?^$\\])", r"\\\1", text)


def _generate_match_pattern(merchant: str) -> str:
    """
    Generate a regex-friendly match pattern from merchant name.

    Handles:
    - Korean/English variations
    - Common abbreviations
    - Case variations
    - Special characters (Issue #154)
    """
    cleaned = _clean_merchant_name(merchant)
    if not cleaned:
        # Escape special characters in the original merchant name
        return _escape_regex_special_chars(merchant)

    # If cleaned name is significantly shorter, use it as pattern
    if len(cleaned) < len(merchant) * 0.7:
        # Escape special characters in both parts and join with OR
        cleaned_escaped = _escape_regex_special_chars(cleaned)
        merchant_escaped = _escape_regex_special_chars(merchant)
        return f"{cleaned_escaped}|{merchant_escaped}"

    # Escape special characters in the cleaned name
    return _escape_regex_special_chars(cleaned)


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


RECURRING_PRIORITY_BOOST = 5


def _deduplicate_rule_name(base_name: str, existing_names: set[str]) -> str:
    """Add a numeric suffix if *base_name* already exists."""
    if base_name not in existing_names:
        return base_name
    for seq in range(2, 100):
        candidate = f"{base_name}_{seq}"
        if candidate not in existing_names:
            return candidate
    return f"{base_name}_99"


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


def _file_id_filter_sql(file_id: str | None) -> str:
    """Return optional SQL filter for import file_id."""
    if file_id is None:
        return ""
    return " AND file_id = ?"


def _merchant_context_query(file_id: str | None = None) -> str:
    """Return the DuckDB aggregation SQL for untagged merchant context."""
    return f"""
        SELECT
            merchant_raw AS merchant,
            COUNT(*) AS transaction_count,
            SUM(ABS(amount)) AS total_amount,
            AVG(ABS(amount)) AS avg_amount,
            COALESCE(STDDEV_SAMP(ABS(amount)), 0.0) AS amount_stddev,
            LIST(DISTINCT substr(CAST(date AS VARCHAR), 1, 7)) AS active_months,
            MODE(major_raw) AS major_raw,
            MODE(minor_raw) AS minor_raw,
            MODE(account) AS payment_method,
            COUNT(*) FILTER (
                WHERE EXTRACT(DOW FROM CAST(date AS DATE)) BETWEEN 1 AND 5
            ) * 1.0 / COUNT(*) AS weekday_pct,
            COUNT(*) FILTER (
                WHERE TRY_CAST(substr(CAST(time AS VARCHAR), 1, 2) AS INTEGER) BETWEEN 11 AND 13
            ) * 1.0 / COUNT(*) AS lunch_pct,
            COUNT(DISTINCT substr(CAST(date AS VARCHAR), 1, 7)) >= 2 AS is_recurring,
            LIST(DISTINCT memo_raw) FILTER (
                WHERE memo_raw IS NOT NULL AND trim(CAST(memo_raw AS VARCHAR)) != ''
            ) AS sample_memos
        FROM transactions
        WHERE (tags_list IS NULL OR len(tags_list) = 0)
          AND {exclude_transfers_sql()}
          AND merchant_raw IS NOT NULL
          AND trim(CAST(merchant_raw AS VARCHAR)) != ''
          AND NOT regexp_matches(CAST(merchant_raw AS VARCHAR), '^[0-9]+$')
          {_file_id_filter_sql(file_id)}
        GROUP BY merchant_raw
        HAVING COUNT(*) >= ?
        ORDER BY COUNT(*) DESC, merchant_raw ASC
        LIMIT ?
    """


def _similar_merchants_query(file_id: str | None = None) -> str:
    """Return the DuckDB SQL for tagged merchants used as context hints."""
    return f"""
        SELECT
            merchant_raw AS merchant,
            COALESCE(
                NULLIF(trim(CAST(category_rule AS VARCHAR)), ''),
                NULLIF(trim(CAST(minor_raw AS VARCHAR)), ''),
                NULLIF(trim(CAST(major_raw AS VARCHAR)), ''),
                '미분류'
            ) AS category,
            AVG(ABS(amount)) AS avg_amount,
            COUNT(*) AS transaction_count
        FROM transactions
        WHERE (tags_list IS NOT NULL AND len(tags_list) > 0)
          AND {exclude_transfers_sql()}
          AND merchant_raw IS NOT NULL
          AND trim(CAST(merchant_raw AS VARCHAR)) != ''
          AND NOT regexp_matches(CAST(merchant_raw AS VARCHAR), '^[0-9]+$')
          {_file_id_filter_sql(file_id)}
        GROUP BY merchant_raw, category
        HAVING COUNT(*) >= 2
    """


def get_suggestion_coverage_stats(
    data_dir: Path,
    file_id: str | None = None,
) -> dict[str, int | float]:
    """Compute total and untagged counts for `rules suggest` via one DuckDB query."""
    from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics

    normalized_data_dir = _normalize_suggest_data_dir(data_dir)
    untagged_sql = "(tags_list IS NULL OR len(tags_list) = 0)"
    sql = f"""
        SELECT
            COUNT(*) AS total_count,
            COUNT(*) FILTER (WHERE {untagged_sql}) AS untagged_count,
            COUNT(*) FILTER (WHERE {exclude_transfers_sql()}) AS suggestable_total_count,
            COUNT(*) FILTER (
                WHERE {exclude_transfers_sql()}
                  AND {untagged_sql}
            ) AS suggestable_untagged_count,
            COUNT(*) FILTER (WHERE NOT {exclude_transfers_sql()}) AS transfer_excluded_count,
            COUNT(*) FILTER (
                WHERE NOT {exclude_transfers_sql()}
                  AND {untagged_sql}
            ) AS transfer_excluded_untagged_count
        FROM transactions
        {"WHERE file_id = ?" if file_id is not None else ""}
    """

    try:
        with DuckDBAnalytics(normalized_data_dir) as analytics:
            params = [file_id] if file_id is not None else []
            result = analytics.conn.execute(sql, params).pl().to_dicts()
    except FileNotFoundError:
        return {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_total_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }

    if not result:
        return {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_total_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }

    total_count = int(result[0]["total_count"] or 0)
    untagged_count = int(result[0]["untagged_count"] or 0)
    suggestable_total_count = int(result[0]["suggestable_total_count"] or 0)
    suggestable_untagged_count = int(result[0]["suggestable_untagged_count"] or 0)
    transfer_excluded_count = int(result[0]["transfer_excluded_count"] or 0)
    transfer_excluded_untagged_count = int(result[0]["transfer_excluded_untagged_count"] or 0)
    coverage_before = 0.0
    if total_count > 0:
        coverage_before = (total_count - untagged_count) / total_count * 100
    suggestable_coverage_before = 0.0
    if suggestable_total_count > 0:
        suggestable_coverage_before = (
            (suggestable_total_count - suggestable_untagged_count) / suggestable_total_count * 100
        )

    return {
        "total_count": total_count,
        "untagged_count": untagged_count,
        "suggestable_total_count": suggestable_total_count,
        "suggestable_untagged_count": suggestable_untagged_count,
        "transfer_excluded_count": transfer_excluded_count,
        "transfer_excluded_untagged_count": transfer_excluded_untagged_count,
        "coverage_before_pct": round(float(coverage_before), 2),
        "suggestable_coverage_before_pct": round(float(suggestable_coverage_before), 2),
    }


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


def _format_suggested_rule_text(suggestion: dict[str, Any]) -> str:
    """Format the suggested_rule for plain-text output."""
    rule = suggestion.get("suggested_rule")
    if not rule:
        return "   suggested_rule: -"
    tags_str = ", ".join(rule.get("tags", []))
    return (
        f"   suggested_rule: {rule['name']} "
        f"(category={rule.get('category', '미분류')}, "
        f"tags=[{tags_str}], priority={rule.get('priority', 80)})"
    )


def format_suggestions_report(suggestions: list[dict[str, Any]]) -> str:
    """Format merchant context as a plain-text report."""
    if not suggestions:
        return "✅ 모든 거래가 태그되었습니다! 규칙 제안이 없습니다."

    lines = [
        "📋 Merchant Context for Rules Suggest",
        "=" * 50,
        "",
        f"총 {len(suggestions)}개의 미태그 가맹점 컨텍스트를 찾았습니다.",
        "",
    ]

    for index, suggestion in enumerate(suggestions, 1):
        major, minor = _banksalad_category_parts(suggestion)
        category_text = " / ".join(part for part in [major, minor] if part) or "미분류"
        similar_text = (
            ", ".join(
                (
                    f"{candidate['merchant']} "
                    f"({candidate['category']}, ₩{candidate['avg_amount']:,.0f})"
                )
                for candidate in suggestion.get("similar_merchants", [])
            )
            or "-"
        )
        memo_text = ", ".join(suggestion.get("sample_memos", [])) or "-"
        active_months = ", ".join(suggestion.get("active_months", [])) or "-"
        time_patterns = suggestion.get("time_patterns", {})

        lines.extend(
            [
                f"{index}. {suggestion['merchant']}",
                (
                    "   거래 "
                    f"{suggestion['transaction_count']}건 | 총액 ₩{suggestion['total_amount']:,.0f}"
                    f" | 평균 ₩{suggestion['avg_amount']:,.0f}"
                    f" | 표준편차 ₩{suggestion['amount_stddev']:,.0f}"
                ),
                f"   활동 월: {active_months}",
                f"   반복 결제 후보: {'예' if suggestion.get('is_recurring') else '아니오'}",
                f"   뱅크샐러드 분류: {category_text}",
                f"   결제수단: {suggestion.get('payment_method') or '-'}",
                (
                    "   시간 패턴: "
                    f"평일 {time_patterns.get('weekday_pct', 0.0):.0%}, "
                    f"점심 {time_patterns.get('lunch_pct', 0.0):.0%}"
                ),
                f"   유사 가맹점: {similar_text}",
                f"   샘플 메모: {memo_text}",
                f"   규칙 패턴: {suggestion['pattern']}",
                (
                    "   권장 액션: 규칙 생성 비추천"
                    if suggestion.get("default_action") == "skip_rule"
                    else "   권장 액션: 규칙 후보"
                ),
                f"   자동 적용 태그: {', '.join(_default_tags_from_suggestion(suggestion))}",
                _format_suggested_rule_text(suggestion),
                "",
            ]
        )

    lines.append(
        "💡 AI 에이전트는 위 컨텍스트를 보고 태그를 결정하거나 --apply --yes를 사용할 수 있습니다."
    )
    return "\n".join(lines)


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


def build_rule_dict_from_suggestion(
    suggestion: dict[str, Any],
    modified_tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Convert a suggestion into the rule payload persisted in rules.yaml."""
    merchant = str(suggestion["merchant"])
    tags = modified_tags if modified_tags is not None else _default_tags_from_suggestion(suggestion)
    category = _default_category_from_suggestion(suggestion)

    rule_dict = {
        "name": get_suggested_rule_name(merchant),
        "match": str(suggestion["pattern"]),
        "fields": ["merchant_raw", "memo_raw"],
        "tags": tags,
        "priority": SUGGESTED_RULE_PRIORITY,
        "created_by": "rules suggest",
        "created_at": datetime.now().isoformat(),
        "notes": (
            f"Auto-suggested for {merchant} ({int(suggestion['transaction_count'])} transactions)"
        ),
    }
    if category:
        rule_dict["category"] = category
    return rule_dict


def apply_suggestion_to_rules(
    suggestion: dict[str, Any],
    rules_path: Path,
    modified_tags: Optional[list[str]] = None,
) -> TagRule:
    """
    Convert a suggestion to a rule and append it to rules.yaml.

    Args:
        suggestion: Merchant context suggestion to apply
        rules_path: Path to rules.yaml file
        modified_tags: Optional modified tags (if user edited them)

    Returns:
        The newly created TagRule object

    Raises:
        ValueError: If rule validation fails
        IOError: If file operations fail
    """
    rule_dict = build_rule_dict_from_suggestion(suggestion, modified_tags=modified_tags)

    return append_rule(rule_dict, rules_path)


# Tag to Banksalad category mapping
# Maps our custom tags to Banksalad's built-in categories
TAG_TO_BANKSALAD_CATEGORY: dict[str, str] = {
    # 카페/커피
    "카페": "식비:카페",
    "커피": "식비:카페",
    # 편의점
    "편의점": "생활:편의점",
    # 식비
    "식비": "식비:기타",
    "배달": "식비:배달",
    "외식": "식비:외식",
    "패스트푸드": "식비:패스트푸드",
    # 쇼핑
    "쇼핑": "쇼핑:기타",
    "온라인쇼핑": "쇼핑:온라인쇼핑",
    "마트": "생활:마트",
    "생활용품": "생활:생활용품",
    # 교통
    "교통": "교통:기타",
    "대중교통": "교통:대중교통",
    "택시": "교통:택시",
    "주유": "교통:주유",
    # 의료/건강
    "의료": "의료/건강:병원",
    "약국": "의료/건강:약국",
    "종합병원": "의료/건강:종합병원",
    # 금융/보험
    "보험": "금융:보험",
    "정기지출": "정기지출:기타",
    # 통신
    "통신": "정기지출:통신",
    # 구독/디지털
    "구독": "정기지출:구독",
    "디지털구독": "정기지출:구독",
    "디지털서비스": "생활:디지털서비스",
    # 기타
    "미분류": "기타:기타",
}


def get_banksalad_category(tags: list[str]) -> str:
    """
    Map tags to the best-matching Banksalad category.

    Args:
        tags: List of tags from our tagging system

    Returns:
        Banksalad category string (e.g., "식비:카페")
    """
    for tag in tags:
        if tag in TAG_TO_BANKSALAD_CATEGORY:
            return TAG_TO_BANKSALAD_CATEGORY[tag]
    return "기타:기타"


def format_rules_as_banksalad_guide(
    rules: list[TagRule],
    include_stats: bool = True,
) -> str:
    """
    Format rules as a Banksalad category mapping guide.

    Args:
        rules: List of TagRule objects
        include_stats: Whether to include match statistics

    Returns:
        Formatted guide string for Banksalad app configuration
    """
    if not rules:
        return "📋 등록된 규칙이 없습니다."

    lines = [
        "┌──────────────────────────────────────────────────────────┐",
        "│ 뱅크샐러드 카테고리 매핑 가이드                              │",
        "├──────────────────────────────────────────────────────────┤",
    ]

    for i, rule in enumerate(rules, 1):
        banksalad_cat = get_banksalad_category(rule.tags)
        tags_str = ", ".join(rule.tags)

        # Stats placeholder (could be enhanced with actual match counts)
        stats_suffix = ""
        if include_stats:
            stats_suffix = ""  # Would need transaction data to calculate

        lines.append(f"│ {i}. {rule.name} → {banksalad_cat}{stats_suffix}")
        lines.append(f'│    키워드: "{rule.match}"')
        lines.append(f"│    이 도구 태그: [{tags_str}]")
        lines.append("│")

    lines.append("└──────────────────────────────────────────────────────────┘")
    lines.append("")
    lines.append("💡 뱅크샐러드 앱에서:")
    lines.append("   설정 → 카테고리 → 자동분류 규칙 → 키워드로 위 패턴 추가")

    return "\n".join(lines)


def format_rules_as_markdown(
    rules: list[TagRule],
    include_stats: bool = True,
) -> str:
    """
    Format rules as Markdown table.

    Args:
        rules: List of TagRule objects
        include_stats: Whether to include match statistics column

    Returns:
        Markdown-formatted table
    """
    if not rules:
        return "# 뱅크샐러드 카테고리 매핑 가이드\n\n등록된 규칙이 없습니다."

    lines = [
        "# 뱅크샐러드 카테고리 매핑 가이드",
        "",
        "| 규칙명 | 패턴 | 권장 카테고리 | 태그 |",
        "|--------|------|--------------|------|",
    ]

    for rule in rules:
        banksalad_cat = get_banksalad_category(rule.tags)
        tags_str = ", ".join(rule.tags)
        lines.append(f"| {rule.name} | {rule.match} | {banksalad_cat} | {tags_str} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 사용 방법")
    lines.append("")
    lines.append("1. 뱅크샐러드 앱 열기")
    lines.append("2. 설정 → 카테고리 → 자동분류 규칙")
    lines.append("3. 위 패턴을 키워드로 추가")

    return "\n".join(lines)
