"""Pattern- and condition-based rule matching for the tagging engine.

Extracted from ``tagging/rules.py`` as the matcher half of the Epic #707
``models + matcher`` split. Sibling modules:

* :mod:`finjuice.pipeline.tagging.models` — data models and schema constants.
* :mod:`finjuice.pipeline.tagging.validator` — per-rule schema validation and
  conflict detection.
* :mod:`finjuice.pipeline.tagging.rules_yaml_io` — reading/writing
  ``rules.yaml`` and loading the ``report_filters`` block.
* :mod:`finjuice.pipeline.tagging.rules` — thin backwards-compatibility shim
  that re-exports the small documented public API surface.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from finjuice.pipeline.tagging.models import (
    NUMERIC_CONDITION_OPERATORS as _NUMERIC_CONDITION_OPERATORS,
)
from finjuice.pipeline.tagging.models import (
    Condition as _Condition,
)
from finjuice.pipeline.tagging.models import (
    TaggingResult as _TaggingResult,
)
from finjuice.pipeline.tagging.models import (
    TagRule,
)
from finjuice.pipeline.tagging.validator import _parse_between_range

logger = logging.getLogger(__name__)


def _check_pattern_match(transaction: Dict[str, Any], rule: TagRule, patterns: List[str]) -> bool:
    """Check if any pattern matches any field in the transaction."""
    if not patterns:
        return False
    for field_name in rule.fields:
        field_value = transaction.get(field_name, "")
        if not field_value:
            continue

        field_value_lower = str(field_value).lower()
        for pattern in patterns:
            if pattern.lower() in field_value_lower:
                return True
    return False


def _check_condition(field_value: Any, condition: _Condition) -> bool:
    """Evaluate a single condition against one field value."""
    if condition.op in _NUMERIC_CONDITION_OPERATORS:
        return _check_numeric_condition(field_value, condition)
    text = str(field_value or "")
    t, v = text.lower(), condition.value.lower()
    op = condition.op
    if op == "contains":
        return v in t
    if op == "not_contains":
        return v not in t
    if op == "is":
        return t == v
    if op == "is_not":
        return t != v
    if op == "starts_with":
        return t.startswith(v)
    if op == "regex":
        return _check_regex(condition.value, text, condition.field)
    return False


def _check_numeric_condition(field_value: Any, condition: _Condition) -> bool:
    """Evaluate numeric conditions against amount-like values."""
    if field_value is None:
        return False
    try:
        num = float(field_value)
    except (TypeError, ValueError):
        return False
    if condition.op == "less_than":
        return _check_less_than(num, condition.value)
    if condition.op == "greater_than":
        return _check_greater_than(num, condition.value)
    minimum, maximum = _parse_between_range(condition.value)
    return minimum is not None and maximum is not None and minimum <= num <= maximum


def _check_less_than(num: float, value: str) -> bool:
    """Evaluate a less-than condition safely."""
    try:
        return num < float(value)
    except (TypeError, ValueError):
        return False


def _check_greater_than(num: float, value: str) -> bool:
    """Evaluate a greater-than condition safely."""
    try:
        return num > float(value)
    except (TypeError, ValueError):
        return False


def _check_regex(pattern: str, text: str, field: str) -> bool:
    """Evaluate a regex condition, logging invalid patterns."""
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        logger.warning("Invalid regex for field '%s': %s", field, pattern)
        return False


def _check_conditions(
    transaction: Dict[str, Any], conditions: List[_Condition], logic: str
) -> bool:
    """Evaluate multiple conditions with AND/OR logic."""
    if not conditions:
        return False
    matches = [
        _check_condition(transaction.get(condition.field, ""), condition)
        for condition in conditions
    ]
    return all(matches) if logic == "all" else any(matches)


def _get_rule_match(transaction: Dict[str, Any], rule: TagRule) -> bool:
    """Check whether a rule matches a transaction."""
    if rule.conditions:
        return _check_conditions(transaction, rule.conditions, rule.logic)
    patterns = [pattern.strip() for pattern in rule.match.split("|") if pattern.strip()]
    return _check_pattern_match(transaction, rule, patterns)


def apply_tagging_rules(transaction: Dict[str, Any], rules: List[TagRule]) -> List[str]:
    """
    Apply tagging rules to a single transaction.

    Strategy:
    - All matching rules contribute tags (not just first match)
    - Rules already sorted by priority
    - Tags are deduplicated while preserving order

    Args:
        transaction: Dict with fields like 'merchant_raw', 'memo_raw', etc
        rules: List of TagRule objects (sorted by priority)

    Returns:
        List of tag strings (deduplicated, order preserved)

    Note:
        For v3 schema with category support, use apply_tagging_rules_v3() instead.

    Example:
        >>> transaction = {
        ...     'merchant_raw': 'METLIFE 보험',
        ...     'memo_raw': '월 납입',
        ... }
        >>> rules = [
        ...     TagRule(name='insurance', match='METLIFE|메트라이프',
        ...             fields=['merchant_raw'], tags=['보험']),
        ...     TagRule(name='monthly', match='월 납입',
        ...             fields=['memo_raw'], tags=['정기지출']),
        ... ]
        >>> apply_tagging_rules(transaction, rules)
        ['보험', '정기지출']
    """
    result = apply_tagging_rules_v3(transaction, rules)
    return result.tags


def apply_tagging_rules_v3(transaction: Dict[str, Any], rules: List[TagRule]) -> _TaggingResult:
    """
    Apply tagging rules to a single transaction (v3 schema with category support).

    Strategy:
    - All matching rules contribute tags (deduplicated, order preserved)
    - Highest-priority matching rule with non-empty category sets category_rule
    - Rules are already sorted by priority (highest first)

    Args:
        transaction: Dict with fields like 'merchant_raw', 'memo_raw', etc
        rules: List of TagRule objects (sorted by priority descending)

    Returns:
        TaggingResult with tags and category_rule

    Example:
        >>> transaction = {
        ...     'merchant_raw': 'METLIFE 보험',
        ...     'memo_raw': '월 납입',
        ... }
        >>> rules = [
        ...     TagRule(name='insurance', match='METLIFE',
        ...             fields=['merchant_raw'], tags=['보험'], category='보험료'),
        ... ]
        >>> result = apply_tagging_rules_v3(transaction, rules)
        >>> result.tags
        ['보험']
        >>> result.category_rule
        '보험료'
    """
    tags: List[str] = []
    category_rule = ""  # First matching rule in priority order with category wins
    matching_rules: List[str] = []

    for rule in rules:
        if not rule.enabled:
            continue

        if _get_rule_match(transaction, rule):
            # Collect tags from all matching rules
            tags.extend(rule.tags)
            matching_rules.append(rule.name)

            # First matching rule in priority order with non-empty category sets category_rule
            if not category_rule and rule.category:
                category_rule = rule.category

    # Deduplicate tags while preserving order
    return _TaggingResult(
        tags=list(dict.fromkeys(tags)),
        category_rule=category_rule,
        matching_rules=matching_rules,
    )
