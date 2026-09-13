"""Standalone budget status projected from one canonical analysis revision."""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.analysis_source import (
    AnalysisReadError,
    analysis_frame,
    analysis_metadata,
    read_analysis_source,
)
from finjuice.pipeline.budget_compute import GoalsFileInvalidError, _assemble_budget_status
from finjuice.pipeline.budget_status_helpers import _budget_actuals_from_frame
from finjuice.pipeline.checkup.repository_inputs import checkup_goals
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import validate_month_literal
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes


def compute_repository_budget_status(
    config: Config,
    *,
    month: str | None,
    evidence_provider: ActivationEvidenceProvider | None = None,
    no_filter: bool = False,
) -> dict[str, Any] | None:
    """Return canonical budget status, or None only for legacy authority."""
    if month is not None:
        month = validate_month_literal(month, param_name="month")
    snapshot = read_analysis_source(config.data_dir, evidence_provider)
    if snapshot is None:
        return None
    try:
        months = snapshot.transactions.partition_months
        resolved = month or (months[-1] if months else date.today().strftime("%Y-%m"))
        goals = checkup_goals(snapshot.goals)
        if goals.exists and goals.document is None:
            raise GoalsFileInvalidError(goals.problems)
        actuals: dict[str, int] = {}
        filters_applied = 0
        if resolved in months:
            filters = ReportFilters() if no_filter else _canonical_filters(snapshot.rules)
            frame = analysis_frame(snapshot, resolved, decode_tags=False)
            actuals, filters_applied = _budget_actuals_from_frame(frame, filters)
        head = snapshot.goals.head
        result = _assemble_budget_status(
            goals,
            {
                "path": None,
                "exists": goals.exists,
                "authority": "repository",
                "selection_state": snapshot.goals.selection_state,
                "revision_id": head.revision_id if head else None,
            },
            actuals,
            month=resolved,
            filters_applied=filters_applied,
        )
        result["_repository_meta"] = analysis_metadata(
            snapshot, "legacy_budget_status.v1", month=resolved
        )
        return result
    except (GoalsFileInvalidError, AnalysisReadError):
        raise
    except Exception:
        raise AnalysisReadError(
            "Repository budget status could not read validated evidence."
        ) from None


def _canonical_filters(selection: PortfolioConfigSnapshot) -> ReportFilters:
    """Honor explicit absence while rejecting uninterpretable canonical filters."""
    if selection.selection_state == "absent" and not selection.revisions:
        return ReportFilters()
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        raise AnalysisReadError("Canonical rules cannot supply budget filters; use --no-filter.")
    try:
        return load_report_filters_bytes(head.content)
    except Exception:
        raise AnalysisReadError(
            "Canonical rules cannot supply budget filters; use --no-filter."
        ) from None
