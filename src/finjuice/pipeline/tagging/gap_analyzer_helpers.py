"""Mismatch-classification helpers for tagging gap analysis.

Owns Banksalad category-part splitting, per-tag mapped categories, mismatch
type/severity constants, and :func:`classify_mismatch`. Gap orchestration,
coverage simulation, and human report formatting stay in
:mod:`finjuice.pipeline.tagging.gap_analyzer`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import dataclass

from finjuice.pipeline.tagging.suggestions import get_banksalad_category

MISMATCH_TYPE_CONFLICT = "conflict"
MISMATCH_TYPE_CATEGORY = "category_mismatch"
MISMATCH_TYPE_MULTI_TAG_NOISE = "multi_tag_noise"
MISMATCH_SEVERITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "none": 3,
}


@dataclass(frozen=True)
class MismatchClassification:
    """Actionability metadata for tagged category mismatches."""

    mismatch_type: str
    mismatch_severity: str
    actionable: bool


def _category_parts(category: str) -> tuple[str, str]:
    """Split a major:minor category string into normalized parts."""
    major, separator, minor = (category or "").partition(":")
    if not separator:
        return major or "기타", ""
    return major or "기타", minor or ""


def _mapped_categories_for_tags(tags: list[str]) -> list[str]:
    """Return unique non-fallback Banksalad categories for individual tags."""
    categories: list[str] = []
    for tag in tags:
        category = get_banksalad_category([tag])
        if category == "기타:기타":
            continue
        if category not in categories:
            categories.append(category)
    return categories


def classify_mismatch(
    tags: list[str],
    raw_category: str,
    expected_category: str,
) -> MismatchClassification:
    """Classify mismatch severity without mutating transactions or rules."""
    mapped_categories = _mapped_categories_for_tags(tags)
    if len(tags) > 1 and raw_category in mapped_categories and raw_category != expected_category:
        return MismatchClassification(
            mismatch_type=MISMATCH_TYPE_MULTI_TAG_NOISE,
            mismatch_severity="low",
            actionable=False,
        )

    raw_major, _raw_minor = _category_parts(raw_category)
    expected_major, _expected_minor = _category_parts(expected_category)
    if raw_major != expected_major and raw_major != "기타" and expected_major != "기타":
        return MismatchClassification(
            mismatch_type=MISMATCH_TYPE_CONFLICT,
            mismatch_severity="high",
            actionable=True,
        )

    return MismatchClassification(
        mismatch_type=MISMATCH_TYPE_CATEGORY,
        mismatch_severity="medium",
        actionable=True,
    )
