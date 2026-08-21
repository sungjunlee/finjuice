"""Unified read-only checkup bundle for AI-oriented runtime orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from finjuice.pipeline.checkup.models import (
    DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
    ActionPriority,
    BudgetPostureSummary,
    BudgetSummary,
    CheckupBundle,
    NetWorthPostureSummary,
    NextAction,
    ObligationConfirmationSummary,
    PipelineFreshnessSummary,
    RecurringOutflowCandidate,
    ReviewPressureSummary,
    ReviewSample,
)

if TYPE_CHECKING:
    from finjuice.pipeline.checkup.compose import collect_checkup_bundle as collect_checkup_bundle

__all__ = [
    "ActionPriority",
    "BudgetPostureSummary",
    "BudgetSummary",
    "CheckupBundle",
    "DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD",
    "NetWorthPostureSummary",
    "NextAction",
    "ObligationConfirmationSummary",
    "PipelineFreshnessSummary",
    "RecurringOutflowCandidate",
    "ReviewPressureSummary",
    "ReviewSample",
    "collect_checkup_bundle",
]


def __getattr__(name: str) -> Any:
    """Load the composer only when callers ask for ``collect_checkup_bundle``.

    Collector modules must remain importable if ``compose.py`` is deleted.
    Eagerly importing the composer here would make every
    ``finjuice.pipeline.checkup.*`` import fail-closed on a missing composer.
    """
    if name == "collect_checkup_bundle":
        from finjuice.pipeline.checkup.compose import collect_checkup_bundle

        return collect_checkup_bundle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
