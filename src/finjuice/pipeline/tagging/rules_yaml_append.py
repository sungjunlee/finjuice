"""YAML append helper for tagging rules.

Owns appending one validated rule dict onto ``rules.yaml``. The public
:func:`append_rule` entrypoint is re-exported from
:mod:`finjuice.pipeline.tagging.rules_yaml_io` so existing callers can keep
importing from that module. Typed loaders stay in
:mod:`finjuice.pipeline.tagging.rules_yaml_load`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_load import load_rules
from finjuice.pipeline.tagging.rules_yaml_roundtrip import add_rule_roundtrip
from finjuice.pipeline.tagging.validator import _validate_rule

logger = logging.getLogger(__name__)


def append_rule(
    new_rule_dict: Dict[str, Any],
    rules_path: Path,
    *,
    authority_data_dir: Path,
) -> TagRule:
    """
    Append new rule to rules.yaml.

    Args:
        new_rule_dict: Dict with rule fields (name, match, fields, tags, priority, etc.)
        rules_path: Path to rules.yaml file
        authority_data_dir: Authoritative data directory used to fence legacy writers.

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
        >>> rule = append_rule(
        ...     new_rule,
        ...     Path("data/rules/rules.yaml"),
        ...     authority_data_dir=Path("data"),
        ... )
    """
    existing_rules = load_rules(rules_path)

    # Validate and create new TagRule (will raise ValueError if invalid)
    validated_dict = _validate_rule(new_rule_dict, len(existing_rules))
    new_rule = TagRule(**validated_dict)

    add_rule_roundtrip(
        validated_dict,
        rules_path,
        authority_data_dir=authority_data_dir,
    )

    logger.info(f"Appended rule '{new_rule.name}' to {rules_path}")
    return new_rule
