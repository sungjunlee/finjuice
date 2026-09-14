"""Inclusion and overlap exclusions. Confirmed relations are never inferred."""

from __future__ import annotations

from collections.abc import Sequence

from finjuice.pipeline.assets.current_view import group_key
from finjuice.pipeline.assets.models import (
    INSTITUTION_SOURCES,
    Exclusion,
    InclusionAssertion,
    Observation,
    ObservationBundle,
)

_HOLDING_KINDS = frozenset({"valuation", "holding_quantity"})


def build_exclusions(
    current: Sequence[Observation],
    bundle: ObservationBundle,
) -> tuple[Exclusion, ...]:
    """Exclude nested/overlapping observations from confirmed net worth."""
    exclusions: dict[str, Exclusion] = {}
    _apply_assertions(current, bundle.inclusions, exclusions)
    _apply_structural_overlaps(current, bundle.inclusions, exclusions)
    return tuple(sorted(exclusions.values(), key=lambda item: item.observation_id))


def lookup_exclusion(
    exclusions: Sequence[Exclusion],
    observation_id: str,
) -> Exclusion | None:
    """Return the exclusion for ``observation_id`` if present."""
    for item in exclusions:
        if item.observation_id == observation_id:
            return item
    return None


def _apply_assertions(
    current: Sequence[Observation],
    inclusions: Sequence[InclusionAssertion],
    exclusions: dict[str, Exclusion],
) -> None:
    current_ids = {item.observation_id for item in current}
    for assertion in inclusions:
        if assertion.review_state == "rejected":
            continue
        if assertion.member_id not in current_ids:
            continue
        if assertion.container_id not in current_ids:
            continue
        exclusions[assertion.member_id] = Exclusion(
            observation_id=assertion.member_id,
            reason=_assertion_reason(assertion),
            assertion_id=assertion.assertion_id,
            review_state=assertion.review_state,
        )


def _assertion_reason(assertion: InclusionAssertion) -> str:
    if assertion.review_state == "unreviewed":
        return "unreviewed_inclusion"
    if assertion.kind == "summary_contains_holdings":
        return "included_in_summary"
    return "overlaps_institution"


def _apply_structural_overlaps(
    current: Sequence[Observation],
    inclusions: Sequence[InclusionAssertion],
    exclusions: dict[str, Exclusion],
) -> None:
    covered = _covered_pairs(inclusions)
    _exclude_summary_holdings(current, covered, exclusions)
    _exclude_manual_institution(current, covered, exclusions)


def _covered_pairs(inclusions: Sequence[InclusionAssertion]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for assertion in inclusions:
        pairs.add((assertion.container_id, assertion.member_id))
        pairs.add((assertion.member_id, assertion.container_id))
    return pairs


def _exclude_summary_holdings(
    current: Sequence[Observation],
    covered: set[tuple[str, str]],
    exclusions: dict[str, Exclusion],
) -> None:
    summaries = [
        item
        for item in current
        if item.measure.kind == "balance" and item.subject.resource_id is None
    ]
    holdings = [
        item
        for item in current
        if item.measure.kind in _HOLDING_KINDS and item.subject.resource_id is not None
    ]
    for summary in summaries:
        for holding in holdings:
            if holding.subject.account_id != summary.subject.account_id:
                continue
            pair = (summary.observation_id, holding.observation_id)
            if pair in covered or (pair[1], pair[0]) in covered:
                continue
            if holding.observation_id in exclusions:
                continue
            exclusions[holding.observation_id] = Exclusion(
                observation_id=holding.observation_id,
                reason="unresolved_summary_holdings_overlap",
                assertion_id=None,
                review_state=None,
            )


def _exclude_manual_institution(
    current: Sequence[Observation],
    covered: set[tuple[str, str]],
    exclusions: dict[str, Exclusion],
) -> None:
    grouped: dict[tuple[str, str, str], list[Observation]] = {}
    for item in current:
        grouped.setdefault(group_key(item), []).append(item)
    for members in grouped.values():
        _exclude_manual_in_group(members, covered, exclusions)


def _exclude_manual_in_group(
    members: Sequence[Observation],
    covered: set[tuple[str, str]],
    exclusions: dict[str, Exclusion],
) -> None:
    manuals = [item for item in members if item.source.kind == "manual"]
    institutions = [item for item in members if item.source.kind in INSTITUTION_SOURCES]
    if not manuals or not institutions:
        return
    for manual in manuals:
        if manual.observation_id in exclusions:
            continue
        if _is_covered(manual, institutions, covered):
            continue
        exclusions[manual.observation_id] = Exclusion(
            observation_id=manual.observation_id,
            reason="unresolved_manual_institution_overlap",
            assertion_id=None,
            review_state=None,
        )


def _is_covered(
    manual: Observation,
    institutions: Sequence[Observation],
    covered: set[tuple[str, str]],
) -> bool:
    for institution in institutions:
        pair = (institution.observation_id, manual.observation_id)
        if pair in covered or (pair[1], pair[0]) in covered:
            return True
    return False
