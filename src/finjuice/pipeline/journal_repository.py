"""Journal snapshot composition from detached canonical financial inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.analysis_source import (
    analysis_frame,
    analysis_metadata,
    read_analysis_source,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.insights import (
    RepositoryStatusSnapshotOptions,
    StatusSnapshot,
    collect_repository_status_snapshot,
)
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes
from finjuice.pipeline.tagging.suggestion_repository import require_finite_values

_GOALS_FIELDS = (
    "structural_savings_monthly_avg",
    "structural_savings_transaction_monthly_avg",
    "recurring_savings_monthly_amount",
    "structural_savings_sources",
    "monthly_avg_consumption_expense",
    "consumption_savings_rate_3mo",
)


class RepositoryJournalError(ValueError):
    """Static failure before a canonical journal snapshot can be saved."""


@dataclass(frozen=True)
class RepositoryJournalSnapshot:
    """Computed snapshot plus source evidence and fields unavailable for saving."""

    snapshot: StatusSnapshot
    warning: str | None
    metadata: dict[str, Any]


def collect_repository_journal_snapshot(
    config: Config, provider: ActivationEvidenceProvider | None
) -> RepositoryJournalSnapshot | None:
    """Read once, returning None only for verified legacy authority."""
    try:
        snapshot = read_analysis_source(config.data_dir, provider)
        return journal_snapshot_from_analysis(snapshot) if snapshot is not None else None
    except Exception:
        raise RepositoryJournalError("Canonical journal snapshot could not be computed.") from None


def journal_snapshot_from_analysis(snapshot: AnalysisReadSnapshot) -> RepositoryJournalSnapshot:
    """Compute from pinned rows and configurations without external reads."""
    try:
        filters = _rules(snapshot.rules)
        frame = analysis_frame(snapshot, decode_tags=False)
        require_finite_values(frame["amount"].to_list())
        content, status = _goals(snapshot.goals)
        result = collect_repository_status_snapshot(
            frame,
            RepositoryStatusSnapshotOptions(
                content, status, filters, active_filter_count=filters.total_rules
            ),
        )
        require_finite_values(result.snapshot.to_dict())
        metadata = analysis_metadata(snapshot, "legacy_journal_snapshot.v1")
        metadata.update(
            calculation_as_of=None,
            calculation_basis="represented_months_with_latest_three_month_rates",
            data_range_basis="included_rows_before_report_filters",
            numeric_policy="legacy_float_display.v1",
            rules_revision_id=snapshot.rules.head.revision_id if snapshot.rules.head else None,
            goals_revision_id=snapshot.goals.head.revision_id if snapshot.goals.head else None,
            rules_parsed_status=snapshot.rules.head.parsed_status if snapshot.rules.head else None,
            goals_parsed_status=snapshot.goals.head.parsed_status if snapshot.goals.head else None,
            goals_state="unavailable"
            if result.warning
            else "absent"
            if _absent(snapshot.goals)
            else "valid",
            active_goals_state="not_computed",
            unavailable_fields=["active_goals", *(_GOALS_FIELDS if result.warning else ())],
            warning=result.warning,
        )
        return RepositoryJournalSnapshot(result.snapshot, result.warning, metadata)
    except Exception:
        raise RepositoryJournalError("Canonical journal snapshot could not be computed.") from None


def _absent(selection: PortfolioConfigSnapshot) -> bool:
    return (
        selection.head is None and selection.selection_state == "absent" and not selection.revisions
    )


def _rules(selection: PortfolioConfigSnapshot) -> ReportFilters:
    if _absent(selection):
        return ReportFilters()
    head = selection.head
    if head is None or selection.selection_state != "selected" or head.parsed_status != "parsed":
        raise RepositoryJournalError("Canonical rules require a valid selection.")
    return load_report_filters_bytes(head.content)


def _goals(selection: PortfolioConfigSnapshot) -> tuple[bytes | None, str | None]:
    if _absent(selection):
        return None, None
    head = selection.head
    if head is None or selection.selection_state != "selected":
        return None, "unselected"
    return head.content, head.parsed_status
