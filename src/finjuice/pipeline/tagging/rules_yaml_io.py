"""YAML I/O for tagging rules and report filters.

This module owns reading ``rules.yaml`` into typed objects and writing it back:

* **Round-trip helpers** — ruamel.yaml-backed save/add/update/remove that
  preserve comments and formatting.
* **Loaders** — :func:`load_rules`, :func:`load_rules_collecting`, and
  :func:`load_report_filters` parse YAML into validated
  :class:`~finjuice.pipeline.tagging.models.TagRule` /
  :class:`~finjuice.pipeline.tagging.models.ReportFilters` objects.

Per-rule schema validation lives in
:mod:`finjuice.pipeline.tagging.validator`; the rule-matching engine lives in
:mod:`finjuice.pipeline.tagging.rules`.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, NoReturn

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from finjuice.pipeline.constants import DEFAULT_RULE_CONFIDENCE, DEFAULT_RULE_PRIORITY
from finjuice.pipeline.tagging.models import (
    VALID_EXCLUDED_CATEGORY_FIELDS,
    VALID_EXCLUDED_DATE_RANGE_FIELDS,
    VALID_EXCLUDED_MERCHANT_FIELDS,
    VALID_REPORT_FILTER_KEYS,
    VALID_REPORT_FILTER_MATCH_TYPES,
    CollectedLoadResult,
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    FiltersValidationError,
    ReportFilters,
    RuleValidationError,
    TagRule,
)
from finjuice.pipeline.tagging.validator import (
    _append_suggestion,
    _candidate_rule_name,
    _extract_suggestion,
    _validate_rule,
)

logger = logging.getLogger(__name__)


def _make_yaml() -> YAML:
    """Create a ruamel.yaml instance configured for round-trip edits."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def _flow_seq(values: list[Any]) -> CommentedSeq:
    """Build an inline YAML sequence."""
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _condition_to_map(condition: Any) -> CommentedMap:
    """Convert a condition object or dict to a YAML mapping."""
    source = condition if isinstance(condition, dict) else condition.__dict__
    condition_map = CommentedMap()
    condition_map["field"] = source["field"]
    condition_map["op"] = source["op"]
    condition_map["value"] = source["value"]
    return condition_map


def _rule_to_map(rule_dict: dict[str, Any]) -> CommentedMap:
    """Convert a rule dict to a YAML mapping with stable key order."""
    rule_map = CommentedMap()
    rule_map["name"] = rule_dict["name"]
    if rule_dict.get("match"):
        rule_map["match"] = rule_dict["match"]
    if rule_dict.get("fields"):
        rule_map["fields"] = _flow_seq(list(rule_dict["fields"]))
    if rule_dict.get("conditions"):
        conditions = CommentedSeq()
        for condition in rule_dict["conditions"]:
            conditions.append(_condition_to_map(condition))
        rule_map["conditions"] = conditions
    if rule_dict.get("logic", "all") != "all":
        rule_map["logic"] = rule_dict["logic"]
    rule_map["tags"] = _flow_seq(list(rule_dict["tags"]))
    rule_map["priority"] = int(rule_dict.get("priority", DEFAULT_RULE_PRIORITY))

    if rule_dict.get("category"):
        rule_map["category"] = rule_dict["category"]
    if rule_dict.get("enabled") is False:
        rule_map["enabled"] = False
    if rule_dict.get("created_by") not in (None, "", "manual"):
        rule_map["created_by"] = rule_dict["created_by"]
    if rule_dict.get("created_at"):
        rule_map["created_at"] = rule_dict["created_at"]

    confidence = rule_dict.get("confidence", DEFAULT_RULE_CONFIDENCE)
    if confidence != DEFAULT_RULE_CONFIDENCE:
        rule_map["confidence"] = float(confidence)
    if rule_dict.get("notes"):
        rule_map["notes"] = rule_dict["notes"]

    return rule_map


def _new_document() -> tuple[CommentedMap, CommentedSeq]:
    """Create an empty rules document."""
    data = CommentedMap()
    data["version"] = 1
    rules = CommentedSeq()
    data["rules"] = rules
    return data, rules


def _load_document(rules_path: Path) -> tuple[YAML, CommentedMap, CommentedSeq]:
    """Load rules.yaml as a round-trip document."""
    yaml = _make_yaml()

    if not rules_path.exists():
        data, rules = _new_document()
        return yaml, data, rules

    with rules_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.load(handle)

    if loaded is None:
        data, rules = _new_document()
        return yaml, data, rules

    if not isinstance(loaded, CommentedMap):
        raise ValueError(f"rules.yaml must contain a mapping, got {type(loaded).__name__}")

    rules_value = loaded.get("rules")
    if rules_value is None:
        rules = CommentedSeq()
        loaded["rules"] = rules
        return yaml, loaded, rules
    if not isinstance(rules_value, CommentedSeq):
        if isinstance(rules_value, list):
            rules = CommentedSeq(rules_value)
            loaded["rules"] = rules
            return yaml, loaded, rules
        raise ValueError(f"'rules' must be a list, got {type(rules_value).__name__}")

    return yaml, loaded, rules_value


def _write_document(yaml: YAML, data: CommentedMap, rules_path: Path) -> None:
    """Persist a round-trip YAML document."""
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    with rules_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)


def _find_rule_indices(rules: CommentedSeq, rule_name: str) -> list[int]:
    """Return all indices whose rule name matches exactly."""
    indices: list[int] = []
    for index, item in enumerate(rules):
        if isinstance(item, dict) and item.get("name") == rule_name:
            indices.append(index)
    return indices


def save_rule_dicts_roundtrip(rule_dicts: list[dict[str, Any]], rules_path: Path) -> None:
    """Write an entire rules document using ruamel.yaml."""
    yaml = _make_yaml()
    data, rules = _new_document()
    for rule_dict in rule_dicts:
        rules.append(_rule_to_map(rule_dict))
    _write_document(yaml, data, rules_path)


def add_rule_roundtrip(rule_dict: dict[str, Any], rules_path: Path) -> None:
    """Append a rule while preserving existing comments and formatting."""
    yaml, data, rules = _load_document(rules_path)
    rules.append(_rule_to_map(rule_dict))
    _write_document(yaml, data, rules_path)


def _update_rule_map_in_place(existing_rule: CommentedMap, rule_dict: dict[str, Any]) -> None:
    """Update a rule map without replacing unchanged nodes and their comments."""
    updated_rule = _rule_to_map(rule_dict)

    for key in list(existing_rule.keys()):
        if key not in updated_rule:
            del existing_rule[key]

    for position, (key, value) in enumerate(updated_rule.items()):
        if key in existing_rule:
            if existing_rule[key] != value:
                existing_rule[key] = value
            continue
        existing_rule.insert(position, key, value)


def update_rule_roundtrip(rule_dict: dict[str, Any], rules_path: Path) -> None:
    """Replace an existing rule by name while preserving surrounding comments."""
    yaml, data, rules = _load_document(rules_path)
    matches = _find_rule_indices(rules, str(rule_dict["name"]))

    if not matches:
        raise KeyError(f"Rule not found: {rule_dict['name']}")
    if len(matches) > 1:
        raise ValueError(f"Multiple rules named '{rule_dict['name']}' found")

    existing_rule = rules[matches[0]]
    if isinstance(existing_rule, CommentedMap):
        _update_rule_map_in_place(existing_rule, rule_dict)
    else:
        rules[matches[0]] = _rule_to_map(rule_dict)
    _write_document(yaml, data, rules_path)


def remove_rule_roundtrip(rule_name: str, rules_path: Path) -> None:
    """Remove a rule by name while preserving surrounding comments."""
    yaml, data, rules = _load_document(rules_path)
    matches = _find_rule_indices(rules, rule_name)

    if not matches:
        raise KeyError(f"Rule not found: {rule_name}")
    if len(matches) > 1:
        raise ValueError(f"Multiple rules named '{rule_name}' found")

    del rules[matches[0]]
    _write_document(yaml, data, rules_path)


# ---------------------------------------------------------------------------
# YAML document loading — rules.yaml -> validated objects
# ---------------------------------------------------------------------------


def _load_yaml_document(rules_path: Path, *, allow_missing_file: bool) -> Any:
    """Load the full YAML document for rules/report_filters parsing.

    Uses PyYAML's ``safe_load`` for plain-data parsing. PyYAML is imported
    locally so the module-level namespace stays free of a ``yaml`` name that
    would collide with the ruamel round-trip helpers above.
    """
    import yaml

    if not rules_path.exists():
        if allow_missing_file:
            logger.info(f"Rules file not found: {rules_path} - using empty rules")
            return {}
        raise FileNotFoundError(f"Rules file not found: {rules_path}")

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(
            f"Invalid YAML syntax in {rules_path}:\n{e}\nCheck for proper indentation and syntax."
        ) from e


def _load_rules_payload(rules_path: Path, *, allow_missing_file: bool) -> List[Any]:
    """Load the raw YAML rules list before per-rule validation."""
    data = _load_yaml_document(rules_path, allow_missing_file=allow_missing_file)
    if not data or not isinstance(data, dict) or "rules" not in data:
        logger.warning(f"No 'rules' key found in {rules_path} - using empty rules")
        return []

    if not isinstance(data["rules"], list):
        raise ValueError(
            f"'rules' must be a list in {rules_path}, got {type(data['rules']).__name__}"
        )

    return data["rules"]


def _collect_validated_rules(raw_rules: List[Any]) -> CollectedLoadResult:
    """Validate raw YAML rule entries while collecting per-rule failures."""
    result = CollectedLoadResult()

    for idx, rule_dict in enumerate(raw_rules):
        try:
            validated_rule = _validate_rule(rule_dict, idx)
            result.rules.append(TagRule(**validated_rule))
        except ValueError as exc:
            result.errors.append(
                RuleValidationError(
                    rule_index=idx,
                    rule_name=_candidate_rule_name(rule_dict, idx),
                    message=str(exc),
                    suggestion=_extract_suggestion(exc),
                )
            )

    result.rules.sort(key=lambda rule: rule.priority, reverse=True)
    return result


def load_rules_collecting(rules_path: Path) -> CollectedLoadResult:
    """
    Load tagging rules from YAML while collecting per-rule validation errors.

    File-level issues such as malformed YAML still raise immediately. Rule-level
    validation failures are accumulated and returned alongside the valid subset.
    """
    raw_rules = _load_rules_payload(rules_path, allow_missing_file=False)
    return _collect_validated_rules(raw_rules)


def load_rules(rules_path: Path) -> List[TagRule]:
    """
    Load tagging rules from YAML file with validation.

    Args:
        rules_path: Path to rules.yaml file

    Returns:
        List of TagRule objects sorted by priority (descending).
        Returns empty list if file doesn't exist.

    Raises:
        ValueError: If YAML is malformed or rules are invalid

    Validation:
        - Required fields: name, tags
        - Requires either 'conditions' or both 'match' and 'fields'
        - Validates field types, priority range, condition operators
        - Checks for unknown fields (warns but doesn't fail)
    """
    raw_rules = _load_rules_payload(rules_path, allow_missing_file=True)
    if not raw_rules:
        return []

    rules: List[TagRule] = []
    for idx, rule_dict in enumerate(raw_rules):
        try:
            validated_rule = _validate_rule(rule_dict, idx)
        except ValueError as exc:
            message = _append_suggestion(str(exc), _extract_suggestion(exc))
            raise ValueError(f"Invalid rule at index {idx} in {rules_path}:\n{message}") from exc
        rules.append(TagRule(**validated_rule))

    return sorted(rules, key=lambda rule: rule.priority, reverse=True)


def summarize_rule_notes(rules_path: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    """Return enabled rule notes for read-only context/review surfaces."""
    if limit <= 0:
        return []

    summaries: list[dict[str, Any]] = []
    for rule in load_rules(rules_path):
        notes = rule.notes.strip()
        if not rule.enabled or not notes:
            continue

        summary: dict[str, Any] = {
            "rule_name": rule.name,
            "notes": notes,
            "tags": list(rule.tags),
        }
        if rule.category:
            summary["category"] = rule.category
        summaries.append(summary)

        if len(summaries) >= limit:
            break

    return summaries


def save_rules(rules: List[TagRule], rules_path: Path) -> None:
    """
    Save rules back to YAML file.

    This is primarily for AI-generated rules in future phases.

    Args:
        rules: List of TagRule objects
        rules_path: Path to save rules.yaml

    Raises:
        OSError: If file cannot be written (permission denied, disk full, etc.)
    """

    def rule_to_dict(r: TagRule) -> Dict[str, Any]:
        """Convert TagRule to dict, only including category if set."""
        d: Dict[str, Any] = {
            "name": r.name,
            "tags": r.tags,
            "priority": r.priority,
        }
        if r.match:
            d["match"] = r.match
        if r.fields:
            d["fields"] = r.fields
        if r.conditions:
            d["conditions"] = [
                {"field": condition.field, "op": condition.op, "value": condition.value}
                for condition in r.conditions
            ]
        if r.logic != "all":
            d["logic"] = r.logic
        # Only include optional fields if they have non-default values
        if r.category:
            d["category"] = r.category
        if not r.enabled:
            d["enabled"] = r.enabled
        if r.created_by != "manual":
            d["created_by"] = r.created_by
        if r.created_at:
            d["created_at"] = r.created_at
        if r.confidence != DEFAULT_RULE_CONFIDENCE:
            d["confidence"] = r.confidence
        if r.notes:
            d["notes"] = r.notes
        return d

    try:
        save_rule_dicts_roundtrip([rule_to_dict(r) for r in rules], rules_path)
        logger.info(f"Saved {len(rules)} rules to {rules_path}")
    except OSError as e:
        logger.error(f"Failed to save rules to {rules_path}: {e}")
        raise


def append_rule(new_rule_dict: Dict[str, Any], rules_path: Path) -> TagRule:
    """
    Append new rule to rules.yaml.

    Args:
        new_rule_dict: Dict with rule fields (name, match, fields, tags, priority, etc.)
        rules_path: Path to rules.yaml file

    Returns:
        The newly created TagRule object

    Raises:
        ValueError: If rule validation fails

    Example:
        >>> new_rule = {
        ...     "name": "starbucks_coffee",
        ...     "match": "스타벅스",
        ...     "fields": ["merchant_raw", "memo_raw"],
        ...     "tags": ["카페", "식비"],
        ...     "priority": 85,
        ... }
        >>> rule = append_rule(new_rule, Path("data/rules/rules.yaml"))
    """
    existing_rules = load_rules(rules_path)

    # Validate and create new TagRule (will raise ValueError if invalid)
    validated_dict = _validate_rule(new_rule_dict, len(existing_rules))
    new_rule = TagRule(**validated_dict)

    add_rule_roundtrip(validated_dict, rules_path)

    logger.info(f"Appended rule '{new_rule.name}' to {rules_path}")
    return new_rule


# ---------------------------------------------------------------------------
# Report filters — rules.yaml report_filters block -> ReportFilters
# ---------------------------------------------------------------------------


def _raise_filters_validation_error(
    rules_path: Path,
    key_path: str,
    message: str,
    *,
    accepted_values: set[str] | None = None,
) -> NoReturn:
    """Raise a structured FiltersValidationError for one schema failure."""
    raise FiltersValidationError(
        rules_path,
        key_path,
        message,
        accepted_values=sorted(accepted_values) if accepted_values else None,
    )


def _validate_filter_required_string(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
) -> str:
    """Validate a required non-empty string in report_filters."""
    if not isinstance(value, str):
        _raise_filters_validation_error(rules_path, key_path, "must be a string")
    stripped = value.strip()
    if not stripped:
        _raise_filters_validation_error(rules_path, key_path, "cannot be empty")
    return stripped


def _normalize_filter_date(value: Any, *, rules_path: Path, key_path: str) -> str:
    """Normalize a YAML date/string value into ISO YYYY-MM-DD form."""
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        _raise_filters_validation_error(rules_path, key_path, "must be an ISO date string")
    stripped = value.strip()
    try:
        return date.fromisoformat(stripped).isoformat()
    except ValueError as exc:
        _raise_filters_validation_error(
            rules_path,
            key_path,
            "must be an ISO date string in YYYY-MM-DD format",
        )
        raise exc  # pragma: no cover


def _validate_filter_mapping(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
    allowed_keys: set[str],
) -> dict[str, Any]:
    """Validate a report_filters entry mapping and reject unknown keys."""
    if not isinstance(value, dict):
        _raise_filters_validation_error(rules_path, key_path, "must be a mapping")

    unknown_keys = set(value) - allowed_keys
    if unknown_keys:
        unknown_key = sorted(unknown_keys)[0]
        _raise_filters_validation_error(
            rules_path,
            f"{key_path}.{unknown_key}",
            "unknown field",
            accepted_values=allowed_keys,
        )

    return value


def _validate_filter_list(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
) -> list[Any]:
    """Normalize an optional report_filters list field."""
    if value is None:
        return []
    if not isinstance(value, list):
        _raise_filters_validation_error(rules_path, key_path, "must be a list")
    return value


def _parse_excluded_merchant_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedMerchantFilter:
    """Parse one excluded_merchants entry."""
    key_path = f"report_filters.excluded_merchants[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_MERCHANT_FIELDS,
    )

    pattern = _validate_filter_required_string(
        entry.get("pattern"),
        rules_path=rules_path,
        key_path=f"{key_path}.pattern",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )

    raw_match_type = entry.get("match_type", "contains")
    match_type = _validate_filter_required_string(
        raw_match_type,
        rules_path=rules_path,
        key_path=f"{key_path}.match_type",
    )
    if match_type not in VALID_REPORT_FILTER_MATCH_TYPES:
        _raise_filters_validation_error(
            rules_path,
            f"{key_path}.match_type",
            f"invalid value {match_type!r}",
            accepted_values=VALID_REPORT_FILTER_MATCH_TYPES,
        )

    since_raw = entry.get("since")
    since = (
        _normalize_filter_date(
            since_raw,
            rules_path=rules_path,
            key_path=f"{key_path}.since",
        )
        if since_raw is not None
        else None
    )

    compiled_pattern: re.Pattern[str] | None = None
    if match_type == "regex":
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            _raise_filters_validation_error(
                rules_path,
                f"{key_path}.pattern",
                f"invalid regex pattern ({exc})",
            )

    return ExcludedMerchantFilter(
        pattern=pattern,
        reason=reason,
        match_type=match_type,
        since=since,
        compiled_pattern=compiled_pattern,
    )


def _parse_excluded_category_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedCategoryFilter:
    """Parse one excluded_categories entry."""
    key_path = f"report_filters.excluded_categories[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_CATEGORY_FIELDS,
    )

    name = _validate_filter_required_string(
        entry.get("name"),
        rules_path=rules_path,
        key_path=f"{key_path}.name",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )
    return ExcludedCategoryFilter(name=name, reason=reason)


def _parse_excluded_date_range_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedDateRangeFilter:
    """Parse one excluded_date_ranges entry."""
    key_path = f"report_filters.excluded_date_ranges[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_DATE_RANGE_FIELDS,
    )

    start = _normalize_filter_date(
        entry.get("start"),
        rules_path=rules_path,
        key_path=f"{key_path}.start",
    )
    end = _normalize_filter_date(
        entry.get("end"),
        rules_path=rules_path,
        key_path=f"{key_path}.end",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )

    if end < start:
        _raise_filters_validation_error(
            rules_path,
            key_path,
            "'end' must be greater than or equal to 'start'",
        )

    return ExcludedDateRangeFilter(start=start, end=end, reason=reason)


def load_report_filters(rules_path: Path) -> ReportFilters:
    """Load declarative report_filters from rules.yaml."""
    data = _load_yaml_document(rules_path, allow_missing_file=True)
    if not data or not isinstance(data, dict) or "report_filters" not in data:
        return ReportFilters()

    raw_filters = data.get("report_filters")
    if raw_filters is None:
        return ReportFilters()
    if not isinstance(raw_filters, dict):
        _raise_filters_validation_error(
            rules_path,
            "report_filters",
            "must be a mapping",
            accepted_values=VALID_REPORT_FILTER_KEYS,
        )

    unknown_keys = set(raw_filters) - VALID_REPORT_FILTER_KEYS
    if unknown_keys:
        unknown_key = sorted(unknown_keys)[0]
        _raise_filters_validation_error(
            rules_path,
            f"report_filters.{unknown_key}",
            "unknown field",
            accepted_values=VALID_REPORT_FILTER_KEYS,
        )

    excluded_merchants = [
        _parse_excluded_merchant_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_merchants"),
                rules_path=rules_path,
                key_path="report_filters.excluded_merchants",
            )
        )
    ]
    excluded_categories = [
        _parse_excluded_category_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_categories"),
                rules_path=rules_path,
                key_path="report_filters.excluded_categories",
            )
        )
    ]
    excluded_date_ranges = [
        _parse_excluded_date_range_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_date_ranges"),
                rules_path=rules_path,
                key_path="report_filters.excluded_date_ranges",
            )
        )
    ]

    return ReportFilters(
        excluded_merchants=excluded_merchants,
        excluded_categories=excluded_categories,
        excluded_date_ranges=excluded_date_ranges,
    )
