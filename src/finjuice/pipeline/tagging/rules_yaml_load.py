"""YAML loaders for tagging rules.

Owns reading ``rules.yaml`` into validated
:class:`~finjuice.pipeline.tagging.models.TagRule` objects. The public
:func:`load_rules`, :func:`load_rules_collecting`, and
:func:`load_rules_bytes` entrypoints are re-exported from
:mod:`finjuice.pipeline.tagging.rules_yaml_io` so existing callers can keep
importing from that module. Report-filters loading stays in
the IO orchestrator.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, List

import yaml
from ruamel.yaml.error import YAMLError as RuamelYAMLError

from finjuice.pipeline.tagging.models import (
    CollectedLoadResult,
    RuleValidationError,
    TagRule,
)
from finjuice.pipeline.tagging.rules_yaml_roundtrip import _make_yaml
from finjuice.pipeline.tagging.validator import (
    _append_suggestion,
    _candidate_rule_name,
    _extract_suggestion,
    _validate_rule,
)
from finjuice.pipeline.yaml_exact import ExactFloatLexeme

logger = logging.getLogger(__name__)


def _load_yaml_document(rules_path: Path, *, allow_missing_file: bool) -> Any:
    """Load the full YAML document for rules/report_filters parsing.

    Uses PyYAML's ``safe_load`` for plain-data parsing.
    """
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
    return _rules_payload_from_document(data, str(rules_path))


def _rules_payload_from_document(data: Any, source: str) -> List[Any]:
    """Validate and return the rules list from one parsed YAML document."""
    if not data or not isinstance(data, dict) or "rules" not in data:
        logger.warning("No 'rules' key found in %s - using empty rules", source)
        return []

    if not isinstance(data["rules"], list):
        raise ValueError(f"'rules' must be a list in {source}, got {type(data['rules']).__name__}")

    return data["rules"]


def load_rules_bytes(content: bytes) -> List[TagRule]:
    """Load validated rules from authoritative exact YAML bytes."""
    try:
        data = _make_yaml().load(content.decode("utf-8"))
    except (UnicodeDecodeError, RuamelYAMLError) as exc:
        raise ValueError(f"Invalid YAML syntax in authoritative rules: {exc}") from exc
    raw_rules = _rules_payload_from_document(data, "authoritative rules")
    rules: List[TagRule] = []
    for index, rule_dict in enumerate(raw_rules):
        try:
            rule_dict = _normalize_exact_rule_metadata(rule_dict, index)
            validated_rule = _validate_rule(rule_dict, index)
        except ValueError as exc:
            message = _append_suggestion(str(exc), _extract_suggestion(exc))
            raise ValueError(
                f"Invalid rule at index {index} in authoritative rules:\n{message}"
            ) from exc
        rules.append(TagRule(**validated_rule))
    return sorted(rules, key=lambda rule: rule.priority, reverse=True)


def _normalize_exact_rule_metadata(rule_dict: Any, index: int) -> Any:
    """Restore float-typed metadata while retaining condition threshold lexemes."""
    if not isinstance(rule_dict, dict):
        return rule_dict
    confidence = rule_dict.get("confidence")
    if not isinstance(confidence, ExactFloatLexeme):
        return rule_dict
    parsed_confidence = float(confidence)
    if not math.isfinite(parsed_confidence):
        raise ValueError(f"Rule at index {index}: 'confidence' must be finite")
    normalized = dict(rule_dict)
    normalized["confidence"] = parsed_confidence
    return normalized


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
