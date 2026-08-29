"""Section loaders for AI-agent context bundles.

Owns journal serialization, goals.yaml loading, rule-note summaries, and
top-pattern queries. Public ``collect_context_bundle`` stays in
:mod:`finjuice.pipeline.context`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT, DuckDBAnalytics
from finjuice.pipeline.analytics.query_builder import build_recent_spend_movers_query
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import (
    summarize_active_goals_payload,
    summarize_financial_metadata_payload,
)
from finjuice.pipeline.journal import load_journal_entries
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters, summarize_rule_notes

logger = logging.getLogger(__name__)

DEFAULT_TOP_PATTERN_LIMIT = 5


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
