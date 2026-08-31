"""Typed models for the read-only checkup bundle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ActionPriority = Literal["high", "medium", "low"]

DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD = 300_000


@dataclass(frozen=True)
class NextAction:
    """One explicit follow-up command suitable for future CLI rendering."""

    domain: str
    priority: ActionPriority
    reason: str
    command: str


@dataclass(frozen=True)
class ReviewSample:
    """Compact review candidate sample."""

    date: str | None
    merchant: str | None
    amount: float | None
    reasons: list[str]


@dataclass(frozen=True)
class BudgetSummary:
    """Budget summary row reused in the checkup bundle."""

    target: int
    actual: int
    remaining: int
    progress_pct: float | None
    status: str


@dataclass(frozen=True)
class RecurringOutflowCandidate:
    """One large recurring outflow that may need user confirmation."""

    label: str
    cadence: str
    amount_range: dict[str, int]
    average_monthly_amount: int
    active_months: list[str]
    active_month_count: int
    transaction_count: int
    suggested_confirmation_question: str


@dataclass(frozen=True)
class PipelineFreshnessSummary:
    """Pipeline freshness summary derived from existing status insights."""

    status: str
    actionable: bool
    pending_import_status: str
    pending_import_files: int
    failed_import_files: int
    transaction_partitions: int
    data_range: str | None
    latest_transaction_date: str | None
    days_since_latest: int | None
    monthly_avg_income: int | None
    monthly_avg_expense: int | None
    savings_rate_3mo: float | None
    active_filters: int
    warning: str | None = None


@dataclass(frozen=True)
class ReviewPressureSummary:
    """Manual-review pressure summary for the latest transaction month."""

    status: str
    actionable: bool
    month: str | None
    total_candidates: int
    needs_review_count: int
    untagged_count: int
    unclassified_count: int
    low_confidence_count: int
    samples: list[ReviewSample] = field(default_factory=list)
    rule_notes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BudgetPostureSummary:
    """Budget posture for the effective month."""

    status: str
    actionable: bool
    month: str
    goals_file_exists: bool
    filters_applied: int
    summary: BudgetSummary | None
    over_budget_categories: list[str] = field(default_factory=list)
    unbudgeted_categories: list[str] = field(default_factory=list)
    warning: str | None = None


@dataclass(frozen=True)
class NetWorthPostureSummary:
    """Net worth posture from snapshots, assets.yaml, and optional goal target."""

    status: str
    actionable: bool
    as_of: str | None
    snapshot_months: int
    assets_file_exists: bool
    asset_count: int
    liability_count: int
    total_assets: float
    total_liabilities: float
    net_worth: float
    target: int | None
    gap_to_target: float | None
    warning: str | None = None


@dataclass(frozen=True)
class ObligationConfirmationSummary:
    """Large recurring outflow candidates for user confirmation."""

    status: str
    actionable: bool
    threshold_monthly_krw: int
    candidate_count: int
    known_obligation_count: int
    candidates: list[RecurringOutflowCandidate] = field(default_factory=list)
    warning: str | None = None


def empty_obligation_confirmation_summary() -> ObligationConfirmationSummary:
    """Return the default quiet obligation confirmation summary."""
    return ObligationConfirmationSummary(
        status="empty",
        actionable=False,
        threshold_monthly_krw=DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
        candidate_count=0,
        known_obligation_count=0,
        candidates=[],
    )


FAST_SKIP_WARNING = (
    "Skipped full detectors in checkup --fast: review, obligations, import preview. "
    "Run `finjuice checkup` for the complete snapshot."
)


def skipped_review_pressure_summary() -> ReviewPressureSummary:
    """Return an explicit skip stand-in for checkup --fast."""
    return ReviewPressureSummary(
        status="skipped",
        actionable=False,
        month=None,
        total_candidates=0,
        needs_review_count=0,
        untagged_count=0,
        unclassified_count=0,
        low_confidence_count=0,
        samples=[],
    )


def skipped_obligation_confirmation_summary() -> ObligationConfirmationSummary:
    """Return an explicit skip stand-in for checkup --fast."""
    return ObligationConfirmationSummary(
        status="skipped",
        actionable=False,
        threshold_monthly_krw=DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
        candidate_count=0,
        known_obligation_count=0,
        candidates=[],
        warning=FAST_SKIP_WARNING,
    )


@dataclass(frozen=True)
class CheckupBundle:
    """Stable Python-level bundle for a future `finjuice checkup` surface."""

    data_dir: str
    actionable: bool
    warnings: list[str]
    next_actions: list[NextAction]
    pipeline: PipelineFreshnessSummary
    review: ReviewPressureSummary
    budget: BudgetPostureSummary
    networth: NetWorthPostureSummary
    obligations: ObligationConfirmationSummary = field(
        default_factory=empty_obligation_confirmation_summary
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bundle for downstream JSON rendering."""
        return asdict(self)
