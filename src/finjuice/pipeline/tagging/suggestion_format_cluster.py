"""Banksalad category mapping and mapping-guide formatting for tag suggestions.

Owns the tag-to-Banksalad category map, :func:`get_banksalad_category`, and
the Banksalad mapping-guide formatters. Plain-text suggestion reports and
rules.yaml serialization stay in
:mod:`finjuice.pipeline.tagging.suggestion_format`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from finjuice.pipeline.tagging.models import TagRule

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
