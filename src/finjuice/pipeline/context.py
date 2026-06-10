"""Structured context bundle collection for external AI agents."""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from finjuice import get_version
from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
from finjuice.pipeline.analytics.query_builder import build_recent_spend_movers_query
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import (
    summarize_active_goals_payload,
    summarize_financial_metadata_payload,
)
from finjuice.pipeline.insights import collect_status_snapshot
from finjuice.pipeline.journal import load_journal_entries
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters, summarize_rule_notes

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_BUDGET = 5000
DEFAULT_JOURNAL_LIMIT = 3
DEFAULT_TOP_PATTERN_LIMIT = 5
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


def _load_journal_context(journal_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    """Load newest-first journal entries with front matter summaries."""
    entries = load_journal_entries(journal_dir)
    return [_serialize_journal_entry(entry.path) for entry in entries[:limit]]


def _serialize_journal_entry(path: Path) -> dict[str, Any]:
    """Return the structured context payload for one journal markdown file."""
    raw_text = path.read_text(encoding="utf-8")
    front_matter, body = _split_front_matter(raw_text)

    summary = body.strip()[:200]
    snapshot = front_matter.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    created = front_matter.get("created")
    data_range = front_matter.get("data_range")

    return {
        "path": str(path.resolve()),
        "filename": path.name,
        "topic": str(front_matter.get("topic") or path.stem),
        "created": str(created) if created is not None else None,
        "data_range": str(data_range) if data_range is not None else None,
        "snapshot": snapshot,
        "summary_200": summary,
    }


def _split_front_matter(raw_text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML front matter and return the remaining markdown body."""
    if not raw_text.startswith("---\n"):
        return {}, raw_text

    try:
        _, raw_front_matter, raw_body = raw_text.split("---\n", 2)
    except ValueError:
        return {}, raw_text

    payload = yaml.safe_load(raw_front_matter) or {}
    front_matter = payload if isinstance(payload, dict) else {}
    return front_matter, raw_body


def _load_goals_context(data_dir: Path) -> dict[str, Any]:
    """Best-effort goals.yaml loading for active goals and safe metadata."""
    goals_path = data_dir / "goals.yaml"
    if not goals_path.exists():
        return {"active_goals": [], "financial_metadata": {}}

    try:
        payload = yaml.safe_load(goals_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Skipping goals.yaml due to parse error: %s", exc)
        return {"active_goals": [], "financial_metadata": {}}

    return {
        "active_goals": summarize_active_goals_payload(payload),
        "financial_metadata": summarize_financial_metadata_payload(payload),
    }


def _load_top_patterns(config: Config) -> list[dict[str, Any]]:
    """Return the strongest 30-day spend movers using the shared DuckDB layer."""
    try:
        report_filters = load_report_filters(config.rules_file)
    except (OSError, ValueError) as exc:
        logger.warning("Skipping context top_patterns due to report filter error: %s", exc)
        report_filters = None

    duckdb_logger = logging.getLogger("finjuice.pipeline.analytics.duckdb_layer")
    previous_duckdb_level = duckdb_logger.level
    duckdb_logger.setLevel(logging.WARNING)
    try:
        with DuckDBAnalytics(config.data_dir, report_filters=report_filters) as analytics:
            rows = analytics.conn.execute(
                build_recent_spend_movers_query(top_n=DEFAULT_TOP_PATTERN_LIMIT)
            ).fetchall()
    except ImportError as exc:
        if str(exc) != DUCKDB_INSTALL_HINT:
            logger.warning("Context top_patterns unavailable: %s", exc)
        return []
    except FileNotFoundError:
        return []
    except (RuntimeError, OSError) as exc:
        logger.warning("Context top_patterns query failed: %s", exc)
        return []
    finally:
        duckdb_logger.setLevel(previous_duckdb_level)

    patterns: list[dict[str, Any]] = []
    for label, delta_krw, direction in rows:
        patterns.append(
            {
                "label": str(label),
                "delta_krw": int(delta_krw),
                "direction": str(direction),
            }
        )
    return patterns


def _load_rule_notes(rules_file: Path) -> list[dict[str, Any]]:
    """Best-effort rule-level metadata notes for AI context."""
    try:
        return summarize_rule_notes(rules_file, limit=5)
    except (OSError, ValueError) as exc:
        logger.warning("Skipping context rule_notes due to rules error: %s", exc)
        return []
