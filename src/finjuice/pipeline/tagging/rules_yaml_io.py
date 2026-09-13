"""YAML I/O for tagging rules and report filters.

This module orchestrates reading ``rules.yaml`` into typed objects and writing
it back. Typed loaders live in
:mod:`finjuice.pipeline.tagging.rules_yaml_load`, typed saves live in
:mod:`finjuice.pipeline.tagging.rules_yaml_save`, and append lives in
:mod:`finjuice.pipeline.tagging.rules_yaml_append`; all are re-exported here
so existing callers can keep importing the public names from this module.
Round-trip dump helpers live in
:mod:`finjuice.pipeline.tagging.rules_yaml_roundtrip` and are re-exported here
so CLI callers can keep importing the public names from this module.
Report-filters schema parsing lives in
:mod:`finjuice.pipeline.tagging.rules_yaml_filters`; the public
:func:`load_report_filters` entrypoint stays here.

* **Loaders** — :func:`load_rules`, :func:`load_rules_collecting`,
  :func:`load_rules_bytes`, and :func:`load_report_filters` parse YAML into validated
  :class:`~finjuice.pipeline.tagging.models.TagRule` /
  :class:`~finjuice.pipeline.tagging.models.ReportFilters` objects.
* **Round-trip helpers** — :func:`save_rule_dicts_roundtrip`,
  :func:`add_rule_roundtrip`, :func:`update_rule_roundtrip`, and
  :func:`remove_rule_roundtrip` preserve comments and formatting.

Per-rule schema validation lives in
:mod:`finjuice.pipeline.tagging.validator`; the rule-matching engine lives in
:mod:`finjuice.pipeline.tagging.rules`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_append import (
    append_rule,  # noqa: F401 — re-exported public YAML API
)
from finjuice.pipeline.tagging.rules_yaml_filters import _parse_report_filters
from finjuice.pipeline.tagging.rules_yaml_load import (
    _load_yaml_document,
    load_rules,
    load_rules_bytes,  # noqa: F401 — re-exported public YAML API
    load_rules_collecting,  # noqa: F401 — re-exported public YAML API
)
from finjuice.pipeline.tagging.rules_yaml_roundtrip import (
    add_rule_roundtrip,  # noqa: F401 — re-exported public dump API
    remove_rule_roundtrip,  # noqa: F401 — re-exported public dump API
    save_rule_dicts_roundtrip,  # noqa: F401 — re-exported public dump API
    update_rule_roundtrip,  # noqa: F401 — re-exported public dump API
)
from finjuice.pipeline.tagging.rules_yaml_save import (
    save_rules,  # noqa: F401 — re-exported public YAML API
)


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


def load_report_filters(rules_path: Path) -> ReportFilters:
    """Load declarative report_filters from rules.yaml."""
    data = _load_yaml_document(rules_path, allow_missing_file=True)
    return _parse_report_filters(data, rules_path)


def load_report_filters_bytes(content: bytes | None) -> ReportFilters:
    """Load report filters from pinned authoritative bytes without live-file fallback."""
    if content is None:
        return ReportFilters()
    try:
        data = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("Invalid YAML syntax in authoritative report filters.") from exc
    return _parse_report_filters(data, Path("authoritative rules"))
