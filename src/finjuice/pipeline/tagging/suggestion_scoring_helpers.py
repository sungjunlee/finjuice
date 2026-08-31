"""Match-pattern generation helpers for `finjuice rules suggest`.

Owns merchant-name cleaning, regex escaping, and suggestion match-pattern
construction. Payment-gateway classification, suggested-rule candidate
payloads, and merchant-context assembly stay in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import re


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
