"""Evaluate asset observations at one as-of revision."""

from __future__ import annotations

from collections.abc import Sequence

from finjuice.pipeline.assets.aggregation import (
    build_lines,
    missing_fx_issues,
    sum_contribution,
    valuation_change_total,
)
from finjuice.pipeline.assets.current_view import select_current
from finjuice.pipeline.assets.inclusion import build_exclusions
from finjuice.pipeline.assets.issues import collect_issues
from finjuice.pipeline.assets.models import (
    EvaluationQuery,
    Observation,
    ObservationBundle,
    ObservationIssue,
    ObservationReport,
)
from finjuice.pipeline.assets.money import parse_decimal


def evaluate_observations(
    bundle: ObservationBundle,
    query: EvaluationQuery,
) -> ObservationReport:
    """Select current evidence and explain confirmed net worth without double counting.

    Meaning corrections are not applied here; call ``apply_changeset`` first.
    """
    _validate_bundle(bundle)
    if query.revision is not None and query.revision != bundle.revision:
        raise ValueError("Query revision does not match the observation bundle.")
    current, evidence = select_current(bundle.observations, query.as_of)
    exclusions = build_exclusions(current, bundle)
    issues = list(collect_issues(bundle, current, evidence, exclusions, query))
    conflict_ids = _conflict_ids(issues)
    lines = build_lines(current, exclusions, query, conflict_ids)
    issues.extend(missing_fx_issues(lines))
    issues.sort(key=lambda item: (item.kind, item.observation_ids, item.detail))
    return ObservationReport(
        as_of=query.as_of,
        revision=bundle.revision,
        valuation_currency=query.valuation_currency,
        current_ids=tuple(item.observation_id for item in current),
        evidence_ids=tuple(item.observation_id for item in evidence),
        exclusions=exclusions,
        lines=lines,
        issues=tuple(issues),
        confirmed_total=sum_contribution(lines, "included"),
        cash_flow_total=sum_contribution(lines, "cash"),
        valuation_change_total=valuation_change_total(evidence, current, query),
    )


def _validate_bundle(bundle: ObservationBundle) -> None:
    seen: set[str] = set()
    for item in bundle.observations:
        if item.observation_id in seen:
            raise ValueError("Duplicate observation_id.")
        seen.add(item.observation_id)
        _validate_observation(item)
    assertion_ids: set[str] = set()
    for assertion in bundle.inclusions:
        if assertion.assertion_id in assertion_ids:
            raise ValueError("Duplicate assertion_id.")
        assertion_ids.add(assertion.assertion_id)


def _validate_observation(item: Observation) -> None:
    if item.lifecycle.supersedes_id == item.observation_id:
        raise ValueError("Observation cannot supersede itself.")
    amount = item.measure.amount
    if amount is not None:
        parse_decimal(amount.amount)
    if item.measure.quantity is not None:
        parse_decimal(item.measure.quantity)


def _conflict_ids(issues: Sequence[ObservationIssue]) -> frozenset[str]:
    ids: set[str] = set()
    for issue in issues:
        if issue.kind == "conflict":
            ids.update(issue.observation_ids)
    return frozenset(ids)
