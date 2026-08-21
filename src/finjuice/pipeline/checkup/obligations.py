"""Obligation-confirmation collector for the checkup bundle."""

from __future__ import annotations

from finjuice.pipeline.checkup.models import (
    DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
    ObligationConfirmationSummary,
)
from finjuice.pipeline.checkup.partitions import read_all_partitions
from finjuice.pipeline.checkup.recurring import _detect_large_recurring_outflow_candidates
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import known_obligation_labels, load_goals_file


def collect_obligation_confirmation(
    config: Config,
    *,
    threshold_monthly_krw: int = DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
) -> ObligationConfirmationSummary:
    """Collect high-level recurring outflow candidates without raw row details."""
    goals_result = load_goals_file(config.goals_file)
    known_labels = known_obligation_labels(goals_result.document)
    known_count = len(goals_result.document.known_obligations or []) if goals_result.document else 0

    source_df = read_all_partitions(config.csv_base_dir)
    if source_df is None or source_df.is_empty():
        return ObligationConfirmationSummary(
            status="empty",
            actionable=False,
            threshold_monthly_krw=threshold_monthly_krw,
            candidate_count=0,
            known_obligation_count=known_count,
            candidates=[],
        )

    candidates = _detect_large_recurring_outflow_candidates(
        source_df,
        threshold_monthly_krw=threshold_monthly_krw,
        known_labels=known_labels,
    )

    return ObligationConfirmationSummary(
        status="needs_confirmation" if candidates else "healthy",
        actionable=bool(candidates),
        threshold_monthly_krw=threshold_monthly_krw,
        candidate_count=len(candidates),
        known_obligation_count=known_count,
        candidates=candidates,
    )
