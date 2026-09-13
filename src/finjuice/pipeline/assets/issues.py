"""Unresolved conflicts, gaps, stale evidence, and unconfirmed relations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from finjuice.pipeline.assets.current_view import group_key
from finjuice.pipeline.assets.models import (
    SNAPSHOT_MEASURES,
    EvaluationQuery,
    Exclusion,
    Observation,
    ObservationBundle,
    ObservationIssue,
)


def collect_issues(
    bundle: ObservationBundle,
    current: Sequence[Observation],
    evidence: Sequence[Observation],
    exclusions: Sequence[Exclusion],
    query: EvaluationQuery,
) -> tuple[ObservationIssue, ...]:
    """Report unresolved observation states. Does not apply meaning corrections."""
    issues: list[ObservationIssue] = []
    issues.extend(_conflicts(evidence))
    issues.extend(_gaps(bundle, current, query))
    issues.extend(_stale_and_partial(current, evidence))
    issues.extend(_unconfirmed_supersessions(evidence))
    issues.extend(_unreviewed_inclusions(bundle))
    issues.extend(_unresolved_overlaps(exclusions))
    issues.sort(key=lambda item: (item.kind, item.observation_ids, item.detail))
    return tuple(issues)


def _conflicts(evidence: Sequence[Observation]) -> list[ObservationIssue]:
    issues: list[ObservationIssue] = []
    superseded = {
        item.lifecycle.supersedes_id
        for item in evidence
        if item.lifecycle.supersedes_id is not None
        and item.lifecycle.confirmation_state == "confirmed"
    }
    grouped: dict[tuple[str, str, str, str], list[Observation]] = defaultdict(list)
    for item in evidence:
        if item.observation_id in superseded:
            continue
        if item.measure.kind not in SNAPSHOT_MEASURES:
            continue
        if item.lifecycle.scope_state != "complete":
            continue
        if item.lifecycle.confirmation_state == "rejected":
            continue
        grouped[(*group_key(item), item.source.kind)].append(item)
    for members in grouped.values():
        issue = _same_as_of_conflict(members)
        if issue is not None:
            issues.append(issue)
    return issues


def _same_as_of_conflict(members: Sequence[Observation]) -> ObservationIssue | None:
    by_as_of: dict[object, list[Observation]] = defaultdict(list)
    for item in members:
        by_as_of[item.time.as_of].append(item)
    for group in by_as_of.values():
        amounts = {_amount_key(item) for item in group}
        if len(amounts) > 1 and len(group) > 1:
            ids = tuple(sorted(item.observation_id for item in group))
            return ObservationIssue(
                kind="conflict",
                observation_ids=ids,
                detail="complete_observations_disagree_at_as_of",
            )
    return None


def _amount_key(item: Observation) -> tuple[Decimal | None, str | None]:
    amount = item.measure.amount
    if amount is None:
        return (item.measure.quantity, None)
    return (amount.amount, amount.currency)


def _gaps(
    bundle: ObservationBundle,
    current: Sequence[Observation],
    query: EvaluationQuery,
) -> list[ObservationIssue]:
    covered = {
        item.subject.account_id
        for item in current
        if item.lifecycle.scope_state == "complete"
    }
    issues: list[ObservationIssue] = []
    for target in bundle.known_targets:
        if target in covered:
            continue
        issues.append(
            ObservationIssue(
                kind="gap",
                observation_ids=(),
                detail=f"missing_complete_observation:{target}:{query.as_of.isoformat()}",
            )
        )
    return issues


def _stale_and_partial(
    current: Sequence[Observation],
    evidence: Sequence[Observation],
) -> list[ObservationIssue]:
    issues: list[ObservationIssue] = []
    current_ids = {item.observation_id for item in current}
    current_by_group: dict[tuple[str, str, str], Observation] = {}
    for item in current:
        if item.measure.kind in SNAPSHOT_MEASURES:
            current_by_group[group_key(item)] = item
    for item in evidence:
        if item.observation_id in current_ids:
            continue
        if item.measure.kind not in SNAPSHOT_MEASURES:
            continue
        winner = current_by_group.get(group_key(item))
        if winner is None:
            continue
        if (
            item.lifecycle.scope_state == "partial"
            and winner.lifecycle.scope_state == "complete"
        ):
            issues.append(
                ObservationIssue(
                    kind="partial_does_not_supersede",
                    observation_ids=(item.observation_id, winner.observation_id),
                    detail="partial_screenshot_remains_evidence",
                )
            )
            continue
        if (
            item.lifecycle.scope_state == "complete"
            and winner.lifecycle.scope_state == "complete"
            and item.time.as_of < winner.time.as_of
        ):
            issues.append(
                ObservationIssue(
                    kind="stale",
                    observation_ids=(item.observation_id, winner.observation_id),
                    detail="older_complete_remains_evidence",
                )
            )
    return issues


def _unconfirmed_supersessions(evidence: Sequence[Observation]) -> list[ObservationIssue]:
    issues: list[ObservationIssue] = []
    for item in evidence:
        target = item.lifecycle.supersedes_id
        if target is None:
            continue
        if item.lifecycle.confirmation_state != "unconfirmed":
            continue
        issues.append(
            ObservationIssue(
                kind="unconfirmed_supersession",
                observation_ids=(item.observation_id, target),
                detail="supersession_requires_changeset_confirmation",
            )
        )
    return issues


def _unreviewed_inclusions(bundle: ObservationBundle) -> list[ObservationIssue]:
    issues: list[ObservationIssue] = []
    for assertion in bundle.inclusions:
        if assertion.review_state != "unreviewed":
            continue
        issues.append(
            ObservationIssue(
                kind="unreviewed_inclusion",
                observation_ids=(assertion.container_id, assertion.member_id),
                detail=f"inclusion_pending_review:{assertion.assertion_id}",
            )
        )
    return issues


def _unresolved_overlaps(exclusions: Sequence[Exclusion]) -> list[ObservationIssue]:
    issues: list[ObservationIssue] = []
    for item in exclusions:
        if not item.reason.startswith("unresolved_"):
            continue
        issues.append(
            ObservationIssue(
                kind="unresolved_overlap",
                observation_ids=(item.observation_id,),
                detail=item.reason,
            )
        )
    return issues
