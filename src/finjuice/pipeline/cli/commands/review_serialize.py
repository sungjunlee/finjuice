"""Review JSON row projection, reason labels, and compact privacy helpers.

Owns the review output row contract: tag normalization, rule-matched flags,
reason/severity labels, and compact privacy projection. Filter predicates
and data loading stay in :mod:`finjuice.pipeline.cli.commands.review`.
Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.review_rendering`.
"""

from __future__ import annotations

import json
from typing import Any

from finjuice.pipeline.cli.privacy import compact_rule_notes


def _normalize_tags(value: Any) -> list[str]:
    """Normalize tags into a JSON-safe list."""
    if isinstance(value, list):
        return [str(tag) for tag in value if tag is not None and str(tag)]

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        if isinstance(decoded, list):
            return [str(tag) for tag in decoded if tag is not None and str(tag)]

    return []


def _row_rule_matched(row: dict[str, Any]) -> bool:
    """Return whether a serialized row has rule-derived tags or category."""
    category_rule = row.get("category_rule")
    if category_rule is not None and str(category_rule).strip():
        return True
    return bool(_normalize_tags(row.get("tags_rule")))


def _is_low_confidence(confidence: Any, threshold: float | None) -> bool:
    """Return whether *confidence* matches the active low-confidence filter."""
    if threshold is None:
        return False
    if confidence is None:
        return True
    try:
        return float(confidence) < threshold
    except (TypeError, ValueError):
        return False


def _review_reasons_for_row(
    row: dict[str, Any],
    *,
    low_confidence_threshold: float | None,
) -> list[str]:
    """Derive machine-readable review reason labels from a transaction row."""
    reasons: list[str] = []
    if row.get("needs_review") == 1:
        reasons.append("needs_review")
    if not _normalize_tags(row.get("tags_final")):
        reasons.append("untagged")
    if row.get("category_final") == "미분류":
        reasons.append("unclassified")
    if _is_low_confidence(row.get("confidence"), low_confidence_threshold):
        reasons.append("low_confidence")
    return reasons


def _review_severity(reasons: list[str]) -> str:
    """Return the highest review severity for a set of review reasons."""
    if "needs_review" in reasons:
        return "high"
    if "untagged" in reasons or "unclassified" in reasons:
        return "medium"
    return "low"


def _serialize_transaction(
    row: dict[str, Any],
    *,
    low_confidence_threshold: float | None,
) -> dict[str, Any]:
    """Project a transaction row into the review output contract."""
    reasons = _review_reasons_for_row(
        row,
        low_confidence_threshold=low_confidence_threshold,
    )
    return {
        "row_hash": row.get("row_hash"),
        "date": row.get("date"),
        "merchant_raw": row.get("merchant_raw"),
        "amount": row.get("amount"),
        "category_final": row.get("category_final"),
        "tags_final": _normalize_tags(row.get("tags_final")),
        "confidence": row.get("confidence"),
        "needs_review": row.get("needs_review"),
        "rule_matched": _row_rule_matched(row),
        "reasons": reasons,
        "severity": _review_severity(reasons),
    }


def _review_reasons_for_serialized(
    row: dict[str, Any],
    *,
    low_confidence_threshold: float | None,
) -> list[str]:
    """Derive compact review reason labels from a serialized review row."""
    existing = row.get("reasons")
    if isinstance(existing, list):
        return [str(reason) for reason in existing if reason is not None]

    reasons: list[str] = []
    if row.get("needs_review") == 1:
        reasons.append("needs_review")
    if not row.get("tags_final"):
        reasons.append("untagged")
    if row.get("category_final") == "미분류":
        reasons.append("unclassified")
    if _is_low_confidence(row.get("confidence"), low_confidence_threshold):
        reasons.append("low_confidence")
    return reasons


def _compact_review_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return review JSON with row-level PII removed."""
    compact = dict(result)
    signals = result.get("signals")
    low_confidence_threshold = (
        signals.get("low_confidence_threshold") if isinstance(signals, dict) else None
    )
    compact["transactions"] = [
        {
            "row_hash": row.get("row_hash"),
            "needs_review": row.get("needs_review"),
            "rule_matched": row.get("rule_matched"),
            "reasons": _review_reasons_for_serialized(
                row,
                low_confidence_threshold=low_confidence_threshold,
            ),
            "severity": row.get("severity"),
        }
        for row in result.get("transactions", [])
    ]
    compact["rule_notes"] = compact_rule_notes(result.get("rule_notes"))
    return compact
