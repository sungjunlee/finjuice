"""Revision-level aggregation that never treats valuation as cash."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from finjuice.pipeline.assets.current_view import group_key
from finjuice.pipeline.assets.inclusion import lookup_exclusion
from finjuice.pipeline.assets.models import (
    NET_WORTH_MEASURES,
    AggregationLine,
    Contribution,
    EvaluationQuery,
    Exclusion,
    Observation,
    ObservationIssue,
)
from finjuice.pipeline.assets.money import valued_amount


def build_lines(
    current: Sequence[Observation],
    exclusions: Sequence[Exclusion],
    query: EvaluationQuery,
    conflict_ids: frozenset[str],
) -> tuple[AggregationLine, ...]:
    """Explain each current observation's contribution at this revision."""
    lines = [_line_for(item, exclusions, query, conflict_ids) for item in current]
    lines.sort(key=lambda item: item.observation_id)
    return tuple(lines)


def sum_contribution(
    lines: Sequence[AggregationLine],
    contribution: Contribution,
) -> Decimal | None:
    """Sum valued amounts for one contribution. None if any included row lacks FX."""
    total = Decimal("0")
    matched = False
    for line in lines:
        if line.contribution != contribution:
            continue
        if line.valued is None:
            return None
        total += line.valued.amount
        matched = True
    return total if matched else Decimal("0")


def missing_fx_issues(lines: Sequence[AggregationLine]) -> tuple[ObservationIssue, ...]:
    """Report current observations that cannot enter the valuation currency."""
    issues: list[ObservationIssue] = []
    for line in lines:
        if line.original is None:
            continue
        if line.valued is not None:
            continue
        if line.contribution in {"quantity_only", "expected"}:
            continue
        issues.append(
            ObservationIssue(
                kind="missing_fx_basis",
                observation_ids=(line.observation_id,),
                detail=f"missing_fx:{line.original.currency}",
            )
        )
    return tuple(issues)


def valuation_change_total(
    evidence: Sequence[Observation],
    current: Sequence[Observation],
    query: EvaluationQuery,
) -> Decimal | None:
    """Market-value delta versus the prior complete valuation. Never cash flow."""
    total = Decimal("0")
    for item in current:
        if item.measure.kind != "valuation":
            continue
        current_value = valued_amount(item.measure, query.valuation_currency)
        if current_value is None:
            return None
        previous = _previous_valuation(evidence, item)
        if previous is None:
            continue
        previous_value = valued_amount(previous.measure, query.valuation_currency)
        if previous_value is None:
            return None
        total += current_value.amount - previous_value.amount
    return total


def _line_for(
    item: Observation,
    exclusions: Sequence[Exclusion],
    query: EvaluationQuery,
    conflict_ids: frozenset[str],
) -> AggregationLine:
    valued = valued_amount(item.measure, query.valuation_currency)
    exclusion = lookup_exclusion(exclusions, item.observation_id)
    contribution = _contribution(item, exclusion, conflict_ids)
    reason = exclusion.reason if exclusion is not None else None
    if contribution == "conflict":
        reason = "conflict_same_as_of"
    policy_id = item.measure.fx.policy_id if item.measure.fx is not None else None
    return AggregationLine(
        observation_id=item.observation_id,
        measure_kind=item.measure.kind,
        original=item.measure.amount,
        valued=valued,
        contribution=contribution,
        exclusion_reason=reason,
        fx_policy_id=policy_id,
    )


_KIND_CONTRIBUTION: dict[str, Contribution] = {
    "holding_quantity": "quantity_only",
    "expected_inflow": "expected",
    "cash_movement": "cash",
}


def _contribution(
    item: Observation,
    exclusion: Exclusion | None,
    conflict_ids: frozenset[str],
) -> Contribution:
    if item.observation_id in conflict_ids:
        return "conflict"
    special = _KIND_CONTRIBUTION.get(item.measure.kind)
    if special is not None:
        return special
    if exclusion is not None or item.measure.kind not in NET_WORTH_MEASURES:
        return "excluded"
    return "included"


def _previous_valuation(
    evidence: Sequence[Observation],
    current: Observation,
) -> Observation | None:
    key = group_key(current)
    previous = [
        item
        for item in evidence
        if group_key(item) == key
        and item.source.kind == current.source.kind
        and item.measure.kind == "valuation"
        and item.lifecycle.scope_state == "complete"
        and item.lifecycle.confirmation_state != "rejected"
        and item.time.as_of < current.time.as_of
    ]
    if not previous:
        return None
    return max(previous, key=lambda item: (item.time.as_of, item.time.collected_at))
