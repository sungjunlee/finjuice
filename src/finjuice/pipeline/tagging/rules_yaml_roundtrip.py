"""Round-trip YAML dump helpers for tagging rules.

Owns ruamel.yaml-backed save/add/update/remove that preserve comments and
formatting. Typed loaders stay in :mod:`finjuice.pipeline.tagging.rules_yaml_io`,
which re-exports the public dump names used by CLI callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from finjuice.pipeline.constants import DEFAULT_RULE_CONFIDENCE, DEFAULT_RULE_PRIORITY


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
