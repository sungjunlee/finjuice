"""CLI report formatting and rule serialization for tag suggestions.

Scoring and candidate generation live in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`. Merchant similarity and
clustering live in :mod:`finjuice.pipeline.tagging.suggestion_similarity`.
This module owns plain-text reports, rules.yaml payloads, and Banksalad
mapping guides.

Callers should keep importing the documented public surface from
:mod:`finjuice.pipeline.tagging.suggestions`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import append_rule
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
