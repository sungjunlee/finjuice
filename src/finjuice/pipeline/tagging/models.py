"""Typed data models shared by the tagging rules engine and its consumers.

This module owns the dataclass and exception surface that other layers
(`storage`, `cli`, `analytics`, …) depend on. Splitting the models out of
``rules.py`` removes the storage→tagging→rules layer inversion that previously
forced ``storage/csv_partition_polars.py`` to import from the rules-matching
engine.

Behavior-preserving extract — historical import paths through
``finjuice.pipeline.tagging.rules`` continue to work via a re-export shim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, List

from finjuice.pipeline.constants import DEFAULT_RULE_CONFIDENCE, DEFAULT_RULE_PRIORITY

# Schema constants describing the rule contract. Kept here because they
# document the model surface; the matching engine in ``rules.py`` references
# them via the existing module-level re-exports.
REQUIRED_RULE_FIELDS: Final = {"name", "tags"}
OPTIONAL_RULE_FIELDS: Final = {
    "match",
    "fields",
    "conditions",
    "logic",
    "priority",
    "enabled",
    "created_by",
    "created_at",
    "confidence",
    "notes",
    "category",
}
VALID_RULE_FIELDS: Final = REQUIRED_RULE_FIELDS | OPTIONAL_RULE_FIELDS
VALID_CONDITION_OPERATORS: Final = {
    "contains",
    "not_contains",
    "is",
    "is_not",
    "starts_with",
    "regex",
    "less_than",
    "greater_than",
    "between",
}
VALID_CONDITION_LOGIC: Final = {"all", "any"}
NUMERIC_CONDITION_OPERATORS: Final = {"less_than", "greater_than", "between"}
VALID_REPORT_FILTER_KEYS: Final = {
    "excluded_merchants",
    "excluded_categories",
    "excluded_date_ranges",
}
VALID_EXCLUDED_MERCHANT_FIELDS: Final = {"pattern", "match_type", "reason", "since"}
VALID_EXCLUDED_CATEGORY_FIELDS: Final = {"name", "reason"}
VALID_EXCLUDED_DATE_RANGE_FIELDS: Final = {"start", "end", "reason"}
VALID_REPORT_FILTER_MATCH_TYPES: Final = {"contains", "exact", "regex"}


class _RuleValidationHintError(ValueError):
    """Internal ValueError subclass that preserves a suggestion for CLI reporting."""

    def __init__(self, message: str, *, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.suggestion = suggestion


class FiltersValidationError(ValueError):
    """Raised when the declarative report_filters block is invalid."""

    def __init__(
        self,
        rules_path: Path,
        key_path: str,
        message: str,
        *,
        accepted_values: list[str] | None = None,
    ) -> None:
        accepted_suffix = ""
        if accepted_values:
            accepted_suffix = f" Accepted values: {accepted_values}."
        super().__init__(
            f"Invalid report_filters in {rules_path} at {key_path}: {message}.{accepted_suffix}"
        )
        self.rules_path = rules_path
        self.key_path = key_path
        self.accepted_values = accepted_values or []


@dataclass
class Condition:
    """Single field-level condition used by tagging rules."""

    field: str
    op: str
    value: str


@dataclass
class TagRule:
    """Single tagging rule definition."""

    name: str
    match: str = ""  # Pipe-separated patterns
    fields: List[str] = field(default_factory=list)  # Fields to search
    tags: List[str] = field(default_factory=list)  # Tags to apply
    conditions: List[Condition] = field(default_factory=list)
    logic: str = "all"  # "all" (AND) or "any" (OR)
    priority: int = DEFAULT_RULE_PRIORITY  # Higher = applied first (default: 50)
    enabled: bool = True

    # NEW in v3: Single category for aggregation (optional)
    # If set, this will be used for category_rule field
    # category_final = COALESCE(category_rule, minor_raw, major_raw, '미분류')
    category: str = ""  # Empty string means not set (will fallback to minor_raw)

    # Metadata (for AI-generated rules in future phases)
    created_by: str = "manual"
    created_at: str = ""
    confidence: float = DEFAULT_RULE_CONFIDENCE  # default: 1.0 (100% confident)
    notes: str = ""


@dataclass
class ExcludedMerchantFilter:
    """Exclude report rows whose merchant matches the configured pattern."""

    pattern: str
    reason: str
    match_type: str = "contains"
    since: str | None = None
    compiled_pattern: re.Pattern[str] | None = field(default=None, repr=False, compare=False)


@dataclass
class ExcludedCategoryFilter:
    """Exclude report rows whose final category matches the configured name."""

    name: str
    reason: str


@dataclass
class ExcludedDateRangeFilter:
    """Exclude report rows whose date falls inside the configured range."""

    start: str
    end: str
    reason: str


@dataclass
class ReportFilters:
    """Typed container for declarative report_filters loaded from rules.yaml."""

    excluded_merchants: list[ExcludedMerchantFilter] = field(default_factory=list)
    excluded_categories: list[ExcludedCategoryFilter] = field(default_factory=list)
    excluded_date_ranges: list[ExcludedDateRangeFilter] = field(default_factory=list)

    @property
    def total_rules(self) -> int:
        """Return the total number of configured exclusion rules."""
        return (
            len(self.excluded_merchants)
            + len(self.excluded_categories)
            + len(self.excluded_date_ranges)
        )

    def is_empty(self) -> bool:
        """Return True when no report filters are configured."""
        return self.total_rules == 0


@dataclass
class RuleValidationError:
    """Single per-rule validation failure collected during rule loading."""

    rule_index: int
    rule_name: str
    message: str
    suggestion: str | None = None


@dataclass
class CollectedLoadResult:
    """Result of loading a rules.yaml file while collecting invalid rules."""

    rules: List[TagRule] = field(default_factory=list)
    errors: List[RuleValidationError] = field(default_factory=list)


@dataclass
class TaggingResult:
    """Result of applying tagging rules to a transaction (v3 schema)."""

    tags: List[str]  # Tags from all matching rules (deduplicated)
    category_rule: str  # Category from highest-priority matching rule with category (or empty)
    matching_rules: List[str] = field(
        default_factory=list
    )  # Names of all rules that matched (in priority order)

    @property
    def has_category(self) -> bool:
        """Check if a category was set by rules."""
        return bool(self.category_rule)


__all__ = [
    "REQUIRED_RULE_FIELDS",
    "OPTIONAL_RULE_FIELDS",
    "VALID_RULE_FIELDS",
    "VALID_CONDITION_OPERATORS",
    "VALID_CONDITION_LOGIC",
    "NUMERIC_CONDITION_OPERATORS",
    "VALID_REPORT_FILTER_KEYS",
    "VALID_EXCLUDED_MERCHANT_FIELDS",
    "VALID_EXCLUDED_CATEGORY_FIELDS",
    "VALID_EXCLUDED_DATE_RANGE_FIELDS",
    "VALID_REPORT_FILTER_MATCH_TYPES",
    "CollectedLoadResult",
    "Condition",
    "ExcludedCategoryFilter",
    "ExcludedDateRangeFilter",
    "ExcludedMerchantFilter",
    "FiltersValidationError",
    "ReportFilters",
    "RuleValidationError",
    "TagRule",
    "TaggingResult",
    "_RuleValidationHintError",
]
