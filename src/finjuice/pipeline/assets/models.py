"""Asset observation structure for as-of, scope, inclusion, and measure kinds.

This module is the M1 domain surface for issue #443. Observations are immutable
evidence. Meaning corrections belong in a separate changeset, not in-place edits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

ScopeState = Literal["complete", "partial", "unknown"]
ConfirmationState = Literal["unconfirmed", "confirmed", "rejected"]
ReviewState = Literal["unreviewed", "confirmed", "rejected"]
SourceKind = Literal[
    "screenshot",
    "institution_export",
    "manual",
    "workbook_summary",
    "workbook_holdings",
]
MeasureKind = Literal[
    "balance",
    "holding_quantity",
    "valuation",
    "cash_movement",
    "right_obligation",
    "expected_inflow",
]
InclusionKind = Literal[
    "summary_contains_holdings",
    "manual_overlaps_institution",
]
CorrectionKind = Literal[
    "confirm_supersession",
    "confirm_inclusion",
    "reject_observation",
    "reclassify_measure",
]
IssueKind = Literal[
    "conflict",
    "gap",
    "stale",
    "unreviewed_inclusion",
    "unconfirmed_supersession",
    "partial_does_not_supersede",
    "unresolved_overlap",
    "missing_fx_basis",
]
Contribution = Literal[
    "included",
    "excluded",
    "cash",
    "expected",
    "quantity_only",
    "conflict",
]
SNAPSHOT_MEASURES: frozenset[MeasureKind] = frozenset(
    {"balance", "holding_quantity", "valuation", "right_obligation"}
)
FLOW_MEASURES: frozenset[MeasureKind] = frozenset({"cash_movement", "expected_inflow"})
NET_WORTH_MEASURES: frozenset[MeasureKind] = frozenset(
    {"balance", "valuation", "right_obligation"}
)
CASH_MEASURES: frozenset[MeasureKind] = frozenset({"cash_movement"})
INSTITUTION_SOURCES: frozenset[SourceKind] = frozenset(
    {"institution_export", "workbook_summary", "workbook_holdings"}
)


@dataclass(frozen=True)
class MoneyAmount:
    """Exact original-currency amount. Never a float."""

    amount: Decimal
    currency: str


@dataclass(frozen=True)
class FxBasis:
    """Named FX conversion used to value an amount into another currency."""

    quote_currency: str
    rate: Decimal
    rate_as_of: date
    policy_id: str


@dataclass(frozen=True)
class ObservationSubject:
    """Account-level or holding-level subject. ``resource_id`` is None for summaries."""

    account_id: str
    resource_id: str | None = None


@dataclass(frozen=True)
class Measure:
    """One observed meaning. Valuation is not cash movement."""

    kind: MeasureKind
    amount: MoneyAmount | None = None
    quantity: Decimal | None = None
    fx: FxBasis | None = None


@dataclass(frozen=True)
class Source:
    """Provenance of one observation. Screenshots stay evidence, not identity."""

    kind: SourceKind
    artifact_id: str | None = None


@dataclass(frozen=True)
class ObservationTime:
    """기준일 (as-of) versus 수집시각 (collected_at)."""

    as_of: date
    collected_at: datetime
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ObservationLifecycle:
    """Scope, confirmation, and explicit supersession. Never inferred from amounts."""

    scope_state: ScopeState
    confirmation_state: ConfirmationState = "unconfirmed"
    supersedes_id: str | None = None


@dataclass(frozen=True)
class Observation:
    """One immutable source-backed observation."""

    observation_id: str
    subject: ObservationSubject
    measure: Measure
    source: Source
    time: ObservationTime
    lifecycle: ObservationLifecycle


@dataclass(frozen=True)
class InclusionAssertion:
    """Explicit summary/holdings or manual/institution overlap. Not inferred."""

    assertion_id: str
    kind: InclusionKind
    container_id: str
    member_id: str
    review_state: ReviewState = "unreviewed"
    reason: str = ""


@dataclass(frozen=True)
class CorrectionOp:
    """One meaning-correction operation applied through a changeset."""

    kind: CorrectionKind
    observation_id: str
    assertion_id: str | None = None
    replacement: Observation | None = None


@dataclass(frozen=True)
class MeaningChangeset:
    """Separate reversible meaning correction. Observations stay immutable."""

    changeset_id: str
    expected_revision: int
    reason: str
    operations: tuple[CorrectionOp, ...]


@dataclass(frozen=True)
class ObservationBundle:
    """Working set of observations, inclusion assertions, and applied changesets."""

    observations: tuple[Observation, ...]
    inclusions: tuple[InclusionAssertion, ...] = ()
    revision: int = 0
    known_targets: tuple[str, ...] = ()
    applied_changesets: tuple[MeaningChangeset, ...] = ()


@dataclass(frozen=True)
class EvaluationQuery:
    """Point-in-time aggregation request in one valuation currency."""

    as_of: date
    valuation_currency: str
    revision: int | None = None


@dataclass(frozen=True)
class Exclusion:
    """Queryable reason an observation was kept out of confirmed net worth."""

    observation_id: str
    reason: str
    assertion_id: str | None = None
    review_state: ReviewState | None = None


@dataclass(frozen=True)
class AggregationLine:
    """One revision-level explanation row for a current observation."""

    observation_id: str
    measure_kind: MeasureKind
    original: MoneyAmount | None
    valued: MoneyAmount | None
    contribution: Contribution
    exclusion_reason: str | None = None
    fx_policy_id: str | None = None


@dataclass(frozen=True)
class ObservationIssue:
    """Unresolved conflict, gap, stale, or unconfirmed observation state."""

    kind: IssueKind
    observation_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class ObservationReport:
    """Deterministic M1 evaluation of observations at one as-of revision."""

    as_of: date
    revision: int
    valuation_currency: str
    current_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    exclusions: tuple[Exclusion, ...]
    lines: tuple[AggregationLine, ...]
    issues: tuple[ObservationIssue, ...]
    confirmed_total: Decimal | None
    cash_flow_total: Decimal | None
    valuation_change_total: Decimal | None

    def exclusion_for(self, observation_id: str) -> Exclusion | None:
        """Return the exclusion record for ``observation_id`` if one exists."""
        for item in self.exclusions:
            if item.observation_id == observation_id:
                return item
        return None
