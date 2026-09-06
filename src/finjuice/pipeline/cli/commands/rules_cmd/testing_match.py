"""Rule-test matching and match-result compute for ``finjuice rules test``.

Owns field projection, row matching, sample serialization, and
month/cross-tag aggregation. The Typer command, JSON payload assembly,
data loading, and error emission stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.testing`, which re-exports
these helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Final

_RULE_EVAL_FIELDS: Final = (
    "merchant_raw",
    "memo_raw",
    "major_raw",
    "minor_raw",
    "type_norm",
    "amount",
    "account",
)


def _normalize_rules_test_tags(value: Any) -> list[str]:
    """Normalize tags_final values to a plain string list."""
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


def _serialize_rules_test_sample(row: dict[str, Any]) -> dict[str, Any]:
    """Project a matched transaction row into the JSON sample contract."""
    return {
        "date": row.get("date"),
        "time": row.get("time"),
        "merchant_raw": row.get("merchant_raw"),
        "amount": row.get("amount"),
        "account": row.get("account"),
        "category_final": row.get("category_final"),
        "tags_final": _normalize_rules_test_tags(row.get("tags_final")),
    }


def _build_rules_test_monthly_distribution(month_counts: Counter[str]) -> dict[str, int]:
    """Return an oldest-first month/count mapping."""
    return {month: month_counts[month] for month in sorted(month_counts)}


def _build_rules_test_cross_tags(cross_counts: Counter[str]) -> list[dict[str, Any]]:
    """Return the top-5 non-rule tags present on matched rows."""
    top_items = sorted(cross_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    return [{"tag": tag, "count": count} for tag, count in top_items]


def _rule_matches_row(row: dict[str, Any], rule: Any) -> bool:
    """Mirror the tagging pipeline's field projection before evaluation."""
    from finjuice.pipeline.tagging.matcher import _get_rule_match

    transaction = {field: row.get(field) for field in _RULE_EVAL_FIELDS}
    return _get_rule_match(transaction, rule)


def _record_rules_test_match(
    row: dict[str, Any],
    *,
    own_tags: set[str],
    sample: list[dict[str, Any]],
    month_counts: Counter[str],
    cross_counts: Counter[str],
    limit: int,
) -> None:
    """Record one matched row into the accumulators."""
    if len(sample) < limit:
        sample.append(_serialize_rules_test_sample(row))
    month_key = str(row.get("date") or "")[:7]
    if re.fullmatch(r"\d{4}-\d{2}", month_key):
        month_counts[month_key] += 1
    cross_counts.update(
        tag for tag in _normalize_rules_test_tags(row.get("tags_rule")) if tag not in own_tags
    )


def _collect_rules_test_matches(df: Any, *, rule: Any, limit: int) -> dict[str, Any]:
    """Evaluate one rule against every row in the loaded scope."""
    own_tags = set(rule.tags)
    sample: list[dict[str, Any]] = []
    month_counts: Counter[str] = Counter()
    cross_counts: Counter[str] = Counter()
    match_count = 0
    for row in df.iter_rows(named=True):
        if not _rule_matches_row(row, rule):
            continue
        match_count += 1
        _record_rules_test_match(
            row,
            own_tags=own_tags,
            sample=sample,
            month_counts=month_counts,
            cross_counts=cross_counts,
            limit=limit,
        )
    return {
        "match_count": match_count,
        "sample": sample,
        "monthly_distribution": _build_rules_test_monthly_distribution(month_counts),
        "cross_tags_top": _build_rules_test_cross_tags(cross_counts),
    }
