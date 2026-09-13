"""Select the current snapshot without letting partial/old evidence overwrite it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from finjuice.pipeline.assets.models import (
    FLOW_MEASURES,
    SNAPSHOT_MEASURES,
    Observation,
)

GroupKey = tuple[str, str, str]


def select_current(
    observations: Sequence[Observation],
    as_of: date,
) -> tuple[tuple[Observation, ...], tuple[Observation, ...]]:
    """Return (current, evidence) for ``as_of``.

    Complete snapshots are the current view. Later partial screenshots remain
    evidence and never replace a complete observation. Flow measures are all
    kept as current events rather than a single winner.
    """
    evidence = tuple(
        item for item in observations if item.time.as_of <= as_of
    )
    rejected = {
        item.observation_id
        for item in evidence
        if item.lifecycle.confirmation_state == "rejected"
    }
    superseded = _confirmed_superseded(evidence)
    eligible = [
        item
        for item in evidence
        if item.observation_id not in rejected
        and item.observation_id not in superseded
        and _is_current_eligible(item)
    ]
    current: list[Observation] = []
    current.extend(_flow_events(eligible))
    current.extend(_snapshot_winners(eligible))
    current.sort(key=lambda item: item.observation_id)
    return tuple(current), evidence


def group_key(item: Observation) -> GroupKey:
    """Stable grouping key for one subject and measure kind."""
    resource_id = item.subject.resource_id or ""
    return (item.subject.account_id, resource_id, item.measure.kind)


def _is_current_eligible(item: Observation) -> bool:
    if item.lifecycle.supersedes_id is None:
        return True
    return item.lifecycle.confirmation_state == "confirmed"


def _confirmed_superseded(evidence: Sequence[Observation]) -> set[str]:
    superseded: set[str] = set()
    by_id = {item.observation_id: item for item in evidence}
    for item in evidence:
        target = item.lifecycle.supersedes_id
        if target is None:
            continue
        if item.lifecycle.confirmation_state != "confirmed":
            continue
        if target in by_id:
            superseded.add(target)
    return superseded


def _flow_events(eligible: Sequence[Observation]) -> list[Observation]:
    return [item for item in eligible if item.measure.kind in FLOW_MEASURES]


def _snapshot_winners(eligible: Sequence[Observation]) -> list[Observation]:
    grouped: dict[GroupKey, list[Observation]] = {}
    for item in eligible:
        if item.measure.kind not in SNAPSHOT_MEASURES:
            continue
        grouped.setdefault(group_key(item), []).append(item)
    winners: list[Observation] = []
    for members in grouped.values():
        winners.extend(_pick_snapshots(members))
    return winners


def _pick_snapshots(members: Sequence[Observation]) -> list[Observation]:
    completes = [item for item in members if item.lifecycle.scope_state == "complete"]
    if not completes:
        winner = max(members, key=_snapshot_sort_key) if members else None
        return [winner] if winner is not None else []
    by_source: dict[str, list[Observation]] = {}
    for item in completes:
        by_source.setdefault(item.source.kind, []).append(item)
    return [max(group, key=_snapshot_sort_key) for group in by_source.values()]


def _snapshot_sort_key(item: Observation) -> tuple[date, object, str]:
    return (item.time.as_of, item.time.collected_at, item.observation_id)
