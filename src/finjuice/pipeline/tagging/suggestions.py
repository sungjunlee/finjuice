"""Backwards-compatibility shim for the tagging-suggestions public API.

Scoring and candidate generation live in
:mod:`finjuice.pipeline.tagging.suggestion_scoring`. Payment-gateway
classification lives in
:mod:`finjuice.pipeline.tagging.suggestion_scoring_classify` and is
re-exported through the scoring module. Suggested-rule candidate payloads
live in :mod:`finjuice.pipeline.tagging.suggestion_scoring_cluster` and are
re-exported through the scoring module. Merchant-context queries
and coverage stats live in :mod:`finjuice.pipeline.tagging.suggestion_queries`
and are re-exported through the scoring module. Merchant similarity and
clustering live in :mod:`finjuice.pipeline.tagging.suggestion_similarity` and
are re-exported through the scoring module. CLI report formatting and
rules.yaml serialization live in
:mod:`finjuice.pipeline.tagging.suggestion_format`. Banksalad category
mapping and mapping-guide formatting live in
:mod:`finjuice.pipeline.tagging.suggestion_format_cluster` and are
re-exported through the format module.

This module re-exports the documented public surface so existing callers can
keep importing from ``finjuice.pipeline.tagging.suggestions``. New code should
import from the owning module directly.
"""

from finjuice.pipeline.tagging.suggestion_format import (
    TAG_TO_BANKSALAD_CATEGORY,
    apply_suggestion_to_rules,
    build_rule_dict_from_suggestion,
    format_rules_as_banksalad_guide,
    format_rules_as_markdown,
    format_suggestions_report,
    get_banksalad_category,
)
from finjuice.pipeline.tagging.suggestion_scoring import (
    GENERIC_LABEL_AMBIGUOUS_REASON,
    MASKED_LABEL_AMBIGUOUS_REASON,
    MERCHANT_CLUSTER_REASON,
    PAYMENT_GATEWAY_AMBIGUOUS_REASON,
    RECURRING_PRIORITY_BOOST,
    SUGGESTED_RULE_PRIORITY,
    TRUNCATED_STORE_CLUSTER_REASON,
    _deduplicate_rule_name,  # noqa: F401 — tests import the private helper via this module.
    _escape_regex_special_chars,  # noqa: F401 — tests import the private helper via this module.
    _generate_match_pattern,  # noqa: F401 — tests import the private helper via this module.
    _merchant_similarity_score,  # noqa: F401 — tests import the private helper via this module.
    _normalize_merchant_for_similarity,  # noqa: F401 — tests import the private helper via this module.
    _sanitize_rule_name,  # noqa: F401 — tests import the private helper via this module.
    build_suggested_rule_field,
    classify_merchant_kind,
    generate_merchant_context,
    get_suggested_rule_name,
    get_suggestion_coverage_stats,
    is_auto_apply_eligible,
)

__all__ = [
    "TAG_TO_BANKSALAD_CATEGORY",
    "GENERIC_LABEL_AMBIGUOUS_REASON",
    "MASKED_LABEL_AMBIGUOUS_REASON",
    "MERCHANT_CLUSTER_REASON",
    "PAYMENT_GATEWAY_AMBIGUOUS_REASON",
    "RECURRING_PRIORITY_BOOST",
    "SUGGESTED_RULE_PRIORITY",
    "TRUNCATED_STORE_CLUSTER_REASON",
    "apply_suggestion_to_rules",
    "build_rule_dict_from_suggestion",
    "build_suggested_rule_field",
    "classify_merchant_kind",
    "format_rules_as_banksalad_guide",
    "format_rules_as_markdown",
    "format_suggestions_report",
    "generate_merchant_context",
    "get_banksalad_category",
    "get_suggested_rule_name",
    "get_suggestion_coverage_stats",
    "is_auto_apply_eligible",
]
