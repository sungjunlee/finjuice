"""Canonical context financial inputs from one detached revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ruamel.yaml.error import YAMLError

from finjuice.pipeline.analysis_source import (
    analysis_frame,
    analysis_metadata,
    read_analysis_source,
)
from finjuice.pipeline.analytics.transaction_frame_registration import register_transaction_frame
from finjuice.pipeline.config import Config
from finjuice.pipeline.context_helpers import (
    goals_context_from_payload,
    require_finite_context_values,
    top_patterns_from_connection,
)
from finjuice.pipeline.goals import load_goals_roundtrip_bytes, validate_goals_payload
from finjuice.pipeline.insights import (
    RepositoryStatusSnapshotOptions,
    collect_repository_status_snapshot,
)
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import (
    load_report_filters_bytes,
    load_rules_bytes,
    rule_notes_from_rules,
)

if TYPE_CHECKING:
    import polars as pl

_GOALS_FIELDS = (
    "structural_savings_monthly_avg",
    "structural_savings_transaction_monthly_avg",
    "recurring_savings_monthly_amount",
    "structural_savings_sources",
    "monthly_avg_consumption_expense",
    "consumption_savings_rate_3mo",
)
_GOALS_WARNING = "Canonical goals are unavailable; dependent context fields are unknown."
_PATTERNS_WARNING = "Context spend patterns are unavailable; run finjuice doctor to inspect DuckDB."
_ERROR = "Canonical context could not read complete validated financial inputs."


class RepositoryContextError(ValueError):
    """Static canonical failure, never authorizing legacy fallback."""


@dataclass(frozen=True)
class RepositoryContextInputs:
    """Detached current financial content, separate from historical journal observations."""

    status_snapshot: dict[str, Any]
    active_goals: list[str] | None
    financial_metadata: dict[str, Any] | None
    rule_notes: list[dict[str, Any]]
    top_patterns: list[dict[str, Any]] | None
    metadata: dict[str, Any]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _Goals:
    content: bytes | None
    parsed_status: str | None
    active_goals: list[str] | None
    financial_metadata: dict[str, Any] | None
    state: str


def collect_repository_context_inputs(
    config: Config, *, evidence_provider: ActivationEvidenceProvider | None = None
) -> RepositoryContextInputs | None:
    """Read one analysis revision; return None only for verified legacy authority."""
    try:
        snapshot = read_analysis_source(config.data_dir, evidence_provider)
        return context_inputs_from_analysis(snapshot) if snapshot is not None else None
    except Exception:
        raise RepositoryContextError(_ERROR) from None


def context_inputs_from_analysis(snapshot: AnalysisReadSnapshot) -> RepositoryContextInputs:
    """Calculate all current financial sections from one frame and selected bytes."""
    try:
        filters, notes = _rules(snapshot.rules)
        goals = _goals(snapshot.goals)
        frame = analysis_frame(snapshot, decode_tags=False)
        require_finite_context_values(frame["amount"].to_list())
        computed = collect_repository_status_snapshot(
            frame,
            RepositoryStatusSnapshotOptions(
                goals.content,
                goals.parsed_status,
                filters,
                active_filter_count=filters.total_rules,
            ),
        )
        status = computed.snapshot.to_dict()
        status["active_goals"] = goals.active_goals
        status["financial_metadata"] = goals.financial_metadata
        unknown_goals = goals.state == "unavailable" or computed.warning is not None
        if unknown_goals:
            for field in _GOALS_FIELDS:
                status[field] = None
            status["active_goals"] = status["financial_metadata"] = None
        patterns, patterns_warning = _patterns(frame, filters)
        warnings = tuple(
            message
            for message in (
                _GOALS_WARNING if unknown_goals else None,
                patterns_warning,
            )
            if message is not None
        )
        require_finite_context_values((status, notes, patterns))
        metadata = _metadata(snapshot, unknown_goals, patterns_warning)
        metadata["warnings"] = list(warnings)
        return RepositoryContextInputs(
            status,
            status["active_goals"],
            status["financial_metadata"],
            notes,
            patterns,
            metadata,
            warnings,
        )
    except Exception:
        raise RepositoryContextError(_ERROR) from None


def _absent(selection: PortfolioConfigSnapshot) -> bool:
    return (
        selection.head is None and selection.selection_state == "absent" and not selection.revisions
    )


def _rules(selection: PortfolioConfigSnapshot) -> tuple[ReportFilters, list[dict[str, Any]]]:
    if _absent(selection):
        return ReportFilters(), []
    head = selection.head
    if head is None or selection.selection_state != "selected" or head.parsed_status != "parsed":
        raise RepositoryContextError(_ERROR)
    rules = load_rules_bytes(head.content)
    return load_report_filters_bytes(head.content), rule_notes_from_rules(rules, limit=5)


def _goals(selection: PortfolioConfigSnapshot) -> _Goals:
    if _absent(selection):
        return _Goals(None, None, [], {}, "absent")
    head = selection.head
    if head is None or selection.selection_state != "selected" or head.parsed_status != "parsed":
        return _Goals(None, "invalid", None, None, "unavailable")
    try:
        _, payload = load_goals_roundtrip_bytes(head.content)
        document, problems = validate_goals_payload(payload)
        if document is None or problems:
            return _Goals(None, "invalid", None, None, "unavailable")
        summary = goals_context_from_payload(payload)
    except (YAMLError, UnicodeError, ValueError, TypeError):
        return _Goals(None, "invalid", None, None, "unavailable")
    require_finite_context_values(summary)
    return _Goals(
        head.content, "parsed", summary["active_goals"], summary["financial_metadata"], "valid"
    )


def _patterns(
    frame: pl.DataFrame, filters: ReportFilters
) -> tuple[list[dict[str, Any]] | None, str | None]:
    # Only inability to import optional DuckDB is an unavailable section.
    # Registration/query/integrity/nonfinite failures remain whole-bundle errors.
    try:
        import duckdb
    except ImportError:
        return None, _PATTERNS_WARNING
    with duckdb.connect(":memory:") as connection:
        register_transaction_frame(connection, frame, filters)
        return top_patterns_from_connection(connection, limit=5), None


def _metadata(
    snapshot: AnalysisReadSnapshot, unknown_goals: bool, patterns_warning: str | None
) -> dict[str, Any]:
    metadata = analysis_metadata(snapshot, "legacy_context_snapshot.v1")
    metadata.update(
        calculation_as_of=None,
        calculation_basis="represented_months_with_latest_three_month_rates",
        data_range_basis="included_rows_before_report_filters",
        numeric_policy="legacy_float_display.v1",
        top_patterns_basis="filtered_nontransfer_spend_latest_date_30day_vs_previous_30day",
        top_patterns_state="unavailable" if patterns_warning else "available",
        goals_state="unavailable"
        if unknown_goals
        else "absent"
        if _absent(snapshot.goals)
        else "valid",
        active_goals_state="unavailable" if unknown_goals else "computed",
        rules_revision_id=snapshot.rules.head.revision_id if snapshot.rules.head else None,
        goals_revision_id=snapshot.goals.head.revision_id if snapshot.goals.head else None,
        unavailable_fields=["active_goals", "financial_metadata", *_GOALS_FIELDS]
        if unknown_goals
        else [],
    )
    if patterns_warning:
        metadata["unavailable_fields"].append("top_patterns")
    return metadata
