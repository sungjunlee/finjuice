"""CLI report formatting and rule serialization for tag suggestions.

Scoring and candidate generation live in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`. Merchant similarity and
clustering live in :mod:`finjuice.pipeline.tagging.suggestion_similarity`.
This module owns plain-text reports and rules.yaml payloads.

Banksalad category mapping and mapping-guide formatting live in
:mod:`finjuice.pipeline.tagging.suggestion_format_cluster` and are re-exported
here so existing callers can keep importing from this module.

Callers should keep importing the documented public surface from
:mod:`finjuice.pipeline.tagging.suggestions`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import append_rule
from finjuice.pipeline.tagging.suggestion_format_cluster import (
    TAG_TO_BANKSALAD_CATEGORY,  # noqa: F401 — re-exported for suggestions callers.
    format_rules_as_banksalad_guide,  # noqa: F401 — re-exported for suggestions callers.
    format_rules_as_markdown,  # noqa: F401 — re-exported for suggestions callers.
    get_banksalad_category,  # noqa: F401 — re-exported for suggestions callers.
)
from finjuice.pipeline.tagging.suggestion_scoring import (
    SUGGESTED_RULE_PRIORITY,
    _banksalad_category_parts,
    _default_category_from_suggestion,
    _default_tags_from_suggestion,
    get_suggested_rule_name,
)


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
        distinct_dates = int(suggestion.get("distinct_dates") or 0)
        transaction_count = int(suggestion["transaction_count"])
        avg_rows_per_date = suggestion.get("avg_rows_per_date")
        if avg_rows_per_date is None:
            avg_rows_per_date = (
                round(transaction_count / distinct_dates, 2) if distinct_dates > 0 else 0.0
            )

        lines.extend(
            [
                f"{index}. {suggestion['merchant']}",
                (
                    "   거래 "
                    f"{transaction_count}건 | 고유일 {distinct_dates}일"
                    f" | 일평균 {float(avg_rows_per_date):.2f}건"
                    f" | 총액 ₩{suggestion['total_amount']:,.0f}"
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
