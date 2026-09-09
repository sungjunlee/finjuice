"""YAML save helper for tagging rules.

Owns writing validated :class:`~finjuice.pipeline.tagging.models.TagRule`
objects back to ``rules.yaml``. The public :func:`save_rules` entrypoint is
re-exported from :mod:`finjuice.pipeline.tagging.rules_yaml_io` so existing
callers can keep importing from that module. Round-trip dump helpers stay in
:mod:`finjuice.pipeline.tagging.rules_yaml_roundtrip`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from finjuice.pipeline.constants import DEFAULT_RULE_CONFIDENCE
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_roundtrip import save_rule_dicts_roundtrip

logger = logging.getLogger(__name__)


def _match_fields(r: TagRule) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
    if r.match:
        extra["match"] = r.match
    if r.fields:
        extra["fields"] = r.fields
    if r.conditions:
        extra["conditions"] = [
            {"field": condition.field, "op": condition.op, "value": condition.value}
            for condition in r.conditions
        ]
    if r.logic != "all":
        extra["logic"] = r.logic
    return extra


def _meta_fields(r: TagRule) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
    if r.category:
        extra["category"] = r.category
    if not r.enabled:
        extra["enabled"] = r.enabled
    if r.created_by != "manual":
        extra["created_by"] = r.created_by
    if r.created_at:
        extra["created_at"] = r.created_at
    if r.confidence != DEFAULT_RULE_CONFIDENCE:
        extra["confidence"] = r.confidence
    if r.notes:
        extra["notes"] = r.notes
    return extra


def rule_to_dict(r: TagRule) -> Dict[str, Any]:
    """Convert TagRule to dict, only including optional fields when set."""
    d: Dict[str, Any] = {
        "name": r.name,
        "tags": r.tags,
        "priority": r.priority,
    }
    d.update(_match_fields(r))
    d.update(_meta_fields(r))
    return d


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
    try:
        save_rule_dicts_roundtrip([rule_to_dict(r) for r in rules], rules_path)
        logger.info(f"Saved {len(rules)} rules to {rules_path}")
    except OSError as e:
        logger.error(f"Failed to save rules to {rules_path}: {e}")
        raise
