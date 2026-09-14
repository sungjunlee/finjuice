"""Human and JSON operator views for pending agent-intake decisions."""

from __future__ import annotations

from typing import Any, Mapping

from finjuice.pipeline.agent.models import (
    DecisionKind,
    IntakeStore,
    OperatorDecision,
    ProposalRecord,
)

_KIND_HINTS = {
    "uncertain_account_mapping": "계좌 매핑을 확정하세요",
    "stale_proposal": "오래된 제안을 현재 revision 기준으로 다시 확인하세요",
    "awaiting_confirmation": "변경 제안을 확정하거나 철회하세요",
}


def pending_decisions(store: IntakeStore) -> tuple[OperatorDecision, ...]:
    """Return one decision per pending proposal, nothing already confirmed."""
    items = [
        _decision_for(proposal, store)
        for proposal in sorted(store.proposals.values(), key=_proposal_sort_key)
        if proposal.status == "pending"
    ]
    return tuple(items)


def operator_payload(store: IntakeStore) -> dict[str, Any]:
    """Return CLI/Hermes JSON that lists only decisions the operator must make."""
    decisions = pending_decisions(store)
    confirmed = [item for item in store.changesets.values() if item.status == "confirmed"]
    return {
        "command": "agent.intake",
        "schema_version": "1.0",
        "revision": store.revision,
        "evidence_count": len(store.evidence),
        "proposal_count": len(store.proposals),
        "applied_changeset_count": len(confirmed),
        "pending_decision_count": len(decisions),
        "decisions": [item.to_dict() for item in decisions],
    }


def render_operator_view(payload: Mapping[str, Any]) -> str:
    """Render a human summary of pending decisions without original source text."""
    count = int(payload.get("pending_decision_count") or 0)
    lines = [f"대기 중인 결정: {count}"]
    decisions = payload.get("decisions") or []
    if not decisions:
        lines.append("필요한 운영 결정이 없습니다.")
        return "\n".join(lines)
    for item in decisions:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        hint = _KIND_HINTS.get(kind, "확인이 필요합니다")
        proposal_id = item.get("proposal_id")
        lines.append(f"- {kind}: {hint} (proposal={proposal_id})")
    return "\n".join(lines)


def _decision_for(proposal: ProposalRecord, store: IntakeStore) -> OperatorDecision:
    evidence = store.evidence[proposal.evidence_id]
    kind: DecisionKind
    if proposal.mapping.status != "certain":
        kind = "uncertain_account_mapping"
    elif proposal.created_revision < store.revision:
        kind = "stale_proposal"
    else:
        kind = "awaiting_confirmation"
    return OperatorDecision(
        kind=kind,
        proposal_id=proposal.proposal_id,
        evidence_id=proposal.evidence_id,
        change_kind=proposal.change_kind,
        source_digest=evidence.source_digest,
        created_revision=proposal.created_revision,
        current_revision=store.revision,
    )


def _proposal_sort_key(proposal: ProposalRecord) -> str:
    return proposal.proposal_id
