"""Structured context bundle collection for external AI agents.

Journal, goals, rule-note, and top-pattern loaders live in
:mod:`finjuice.pipeline.context_helpers` and are re-exported here so existing
callers can keep importing from this module.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

from finjuice import get_version
from finjuice.pipeline.config import Config
from finjuice.pipeline.context_helpers import (
    DEFAULT_TOP_PATTERN_LIMIT,  # noqa: F401 — re-exported for existing context imports
    _load_goals_context,
    _load_journal_context,
    _load_rule_notes,
    _load_top_patterns,
    _serialize_journal_entry,  # noqa: F401 — re-exported for existing context imports
    _split_front_matter,  # noqa: F401 — re-exported for existing context imports
)
from finjuice.pipeline.insights import collect_status_snapshot

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_BUDGET = 5000
DEFAULT_JOURNAL_LIMIT = 3
_STATUS_SNAPSHOT_DROP_ORDER = (
    "top_categories",
    "structural_savings_sources",
    "consumption_savings_rate_3mo",
    "monthly_avg_consumption_expense",
    "structural_savings_monthly_avg",
    "structural_savings_transaction_monthly_avg",
    "recurring_savings_monthly_amount",
    "residual_savings_rate_3mo",
    "savings_rate_3mo",
    "active_filters",
    "data_range",
    "monthly_avg_income",
    "monthly_avg_expense",
)


def estimate_tokens(payload: Any) -> int:
    """Estimate prompt tokens with a simple character-count heuristic."""
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return math.ceil(len(text) / 4)


def resolve_context_budget(requested_budget: int | None) -> int:
    """Resolve the active context budget from CLI flag, env var, or default."""
    if requested_budget is not None:
        return requested_budget

    raw_budget = os.getenv("FINJUICE_CONTEXT_BUDGET", "").strip()
    if not raw_budget:
        return DEFAULT_CONTEXT_BUDGET

    try:
        parsed_budget = int(raw_budget)
    except ValueError:
        logger.warning("Ignoring invalid FINJUICE_CONTEXT_BUDGET value: %s", raw_budget)
        return DEFAULT_CONTEXT_BUDGET

    if parsed_budget < 1:
        logger.warning("Ignoring non-positive FINJUICE_CONTEXT_BUDGET value: %s", raw_budget)
        return DEFAULT_CONTEXT_BUDGET

    return parsed_budget


def collect_context_bundle(
    config: Config,
    *,
    journal_limit: int = DEFAULT_JOURNAL_LIMIT,
    budget: int = DEFAULT_CONTEXT_BUDGET,
) -> dict[str, Any]:
    """Collect and truncate the AI-agent context bundle for the given config."""
    snapshot_result = collect_status_snapshot(config)
    goals_context = _load_goals_context(config.data_dir)
    active_goals = goals_context["active_goals"]
    financial_metadata = goals_context["financial_metadata"]
    status_snapshot = snapshot_result.snapshot.to_dict()
    status_snapshot["active_goals"] = list(active_goals)
    status_snapshot["financial_metadata"] = financial_metadata

    bundle: dict[str, Any] = {
        "journals": _load_journal_context(config.journal_dir, limit=journal_limit),
        "status_snapshot": status_snapshot,
        "active_goals": list(active_goals),
        "financial_metadata": financial_metadata,
        "rule_notes": _load_rule_notes(config.rules_file),
        "top_patterns": _load_top_patterns(config),
    }

    dropped_sections: list[str] = []
    sections, total_tokens = _measure_sections(bundle)

    if total_tokens > budget and bundle["top_patterns"]:
        bundle["top_patterns"] = []
        dropped_sections.append("top_patterns")
        sections, total_tokens = _measure_sections(bundle)

    while total_tokens > budget and bundle["journals"]:
        dropped_journal = bundle["journals"].pop()
        dropped_sections.append(f"journals:{dropped_journal['filename']}")
        sections, total_tokens = _measure_sections(bundle)

    for field_name in _STATUS_SNAPSHOT_DROP_ORDER:
        if total_tokens <= budget:
            break
        if field_name not in bundle["status_snapshot"]:
            continue
        bundle["status_snapshot"].pop(field_name)
        dropped_sections.append(f"status_snapshot.{field_name}")
        sections, total_tokens = _measure_sections(bundle)

    bundle["_meta"] = {
        "schema_version": "1.0",
        "finjuice_version": get_version(),
        "command": "context",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_tokens_est": total_tokens,
        "budget": budget,
        "truncated": bool(dropped_sections),
        "dropped_sections": dropped_sections,
        "sections": sections,
    }
    return bundle


def _measure_sections(bundle: dict[str, Any]) -> tuple[dict[str, dict[str, int]], int]:
    """Return per-section token counts plus the aggregate estimate."""
    section_tokens = {
        "journals": {"tokens": estimate_tokens(bundle["journals"])},
        "status_snapshot": {"tokens": estimate_tokens(bundle["status_snapshot"])},
        "active_goals": {"tokens": estimate_tokens(bundle["active_goals"])},
        "financial_metadata": {"tokens": estimate_tokens(bundle["financial_metadata"])},
        "rule_notes": {"tokens": estimate_tokens(bundle["rule_notes"])},
        "top_patterns": {"tokens": estimate_tokens(bundle["top_patterns"])},
    }
    total_tokens = sum(section["tokens"] for section in section_tokens.values())
    return section_tokens, total_tokens
