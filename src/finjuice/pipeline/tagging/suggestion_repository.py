"""Pinned canonical inputs for merchant suggestion calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from finjuice.pipeline.analysis_source import (
    analysis_frame,
    analysis_metadata,
    read_analysis_source,
)
from finjuice.pipeline.analytics.transaction_frame_registration import register_transaction_frame
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes
from finjuice.pipeline.tagging.suggest_compute_stats import _augment_suggestion_stats
from finjuice.pipeline.tagging.suggestion_existing_rules import existing_rule_context
from finjuice.pipeline.tagging.suggestion_queries import (
    coverage_stats_from_connection,
    merchant_context_from_connection,
)
from finjuice.pipeline.tagging.suggestion_scoring import score_merchant_contexts


@dataclass(frozen=True)
class SuggestionReadOptions:
    """Existing read options independent of rendering and rule application."""

    top_n: int = 10
    min_count: int = 1
    file_id: str | None = None


@dataclass(frozen=True)
class RepositorySuggestions:
    """Detached calculation results and their authoritative revision."""

    stats: dict[str, Any]
    suggestions: list[dict[str, Any]]
    metadata: dict[str, Any]


def read_repository_suggestions(
    data_dir: Path,
    provider: ActivationEvidenceProvider | None,
    options: SuggestionReadOptions,
) -> RepositorySuggestions | None:
    """Read one analysis revision; None means legacy authority only."""
    try:
        snapshot = read_analysis_source(data_dir, provider)
        return None if snapshot is None else suggestions_from_snapshot(snapshot, options)
    except Exception:
        raise ValueError("Canonical suggestions could not be evaluated.") from None


def suggestions_from_snapshot(
    snapshot: AnalysisReadSnapshot, options: SuggestionReadOptions
) -> RepositorySuggestions:
    """Calculate using an existing detached revision without opening another reader."""
    rules = _selected_rules(snapshot.rules)
    frame = analysis_frame(snapshot, decode_tags=False)
    stats, suggestions = suggestions_from_frame(frame, rules, options)
    metadata = analysis_metadata(snapshot, "legacy_rules_suggest.v1")
    head = snapshot.rules.head
    metadata["rules_revision_id"] = head.revision_id if head is not None else None
    return RepositorySuggestions(stats, suggestions, metadata)


def suggestions_from_frame(
    frame: pl.DataFrame, rules: list[TagRule], options: SuggestionReadOptions
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reuse existing SQL/scoring on trusted detached inputs for composition callers."""
    patterns, names = existing_rule_context(rules)
    with duckdb.connect(":memory:") as connection:
        register_transaction_frame(connection, frame, ReportFilters())
        stats = _augment_suggestion_stats(
            coverage_stats_from_connection(connection, options.file_id)
        )
        _require_finite(stats)
        if stats["suggestable_untagged_count"] == 0:
            return stats, []
        contexts, tagged = merchant_context_from_connection(
            connection, options.top_n, options.min_count, options.file_id
        )
        _require_finite((contexts, tagged))
        suggestions = score_merchant_contexts(contexts, tagged, patterns, names, options.top_n)
        _require_finite(suggestions)
        return stats, suggestions


def _selected_rules(selection: PortfolioConfigSnapshot) -> list[TagRule]:
    if selection.selection_state == "absent" and not selection.revisions:
        return []
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        raise ValueError("Canonical rules require a valid selected configuration.")
    return load_rules_bytes(head.content)


def _require_finite(value: Any) -> None:
    """Reject unsupported numeric aggregates instead of publishing NaN or infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Suggestion aggregates must be finite.")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("Suggestion aggregates must be finite.")
    if isinstance(value, dict):
        for item in value.values():
            _require_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_finite(item)
