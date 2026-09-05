"""Report-filter loaders for financial snapshot collection.

Owns configured-filter loading, active-filter counting, and the on-disk
report_filters.yaml lookup used by status snapshots. Snapshot dataclasses
and ``collect_status_snapshot`` stay in :mod:`finjuice.pipeline.insights`,
which re-exports the names used by existing callers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters

logger = logging.getLogger(__name__)

_REPORT_FILTER_CANDIDATES = (
    ("report_filters.yaml",),
    ("report_filters.yml",),
    ("metadata", "report_filters.yaml"),
    ("metadata", "report_filters.yml"),
)


def _load_configured_report_filters(config: Config) -> ReportFilters:
    """Best-effort loader for status snapshot consumers outside the CLI layer."""
    try:
        return load_report_filters(config.rules_file)
    except (OSError, ValueError) as exc:
        logger.warning("Skipping report_filters in snapshot due to load error: %s", exc)
        return ReportFilters()


def _count_active_filters(data_dir: Path) -> int:
    """Best-effort count of active report filters if the file exists."""
    rules_path = data_dir / "rules.yaml"
    if rules_path.exists():
        try:
            filters = load_report_filters(rules_path)
        except (OSError, ValueError) as exc:
            logger.warning("Could not parse report filters from %s: %s", rules_path, exc)
        else:
            if not filters.is_empty():
                return filters.total_rules

    payload = _load_report_filters(data_dir)
    if payload is None:
        return 0

    if isinstance(payload, list):
        return sum(1 for item in payload if _filter_enabled(item))

    if isinstance(payload, dict):
        if isinstance(payload.get("filters"), list):
            return sum(1 for item in payload["filters"] if _filter_enabled(item))
        if isinstance(payload.get("report_filters"), list):
            return sum(1 for item in payload["report_filters"] if _filter_enabled(item))
        return sum(1 for value in payload.values() if _filter_enabled(value))

    return 0


def _load_report_filters(data_dir: Path) -> Any | None:
    """Load report filters from common on-disk locations."""
    for parts in _REPORT_FILTER_CANDIDATES:
        candidate = data_dir.joinpath(*parts)
        if not candidate.exists():
            continue
        try:
            return yaml.safe_load(candidate.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not parse report filters file %s: %s", candidate, exc)
            return None
    return None


def _filter_enabled(payload: Any) -> bool:
    """Return True when a filter payload looks active."""
    if payload is None:
        return False
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, dict):
        enabled = payload.get("enabled")
        return enabled is not False
    return True
