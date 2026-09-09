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
