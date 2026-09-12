"""Parse and emit privacy-safe reconcile JSON."""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.reconcile.models import EvidenceItem, MatchGroup, ReconcileReport
from finjuice.pipeline.reconcile.money import parse_money


def evidence_from_payload(payload: dict[str, Any]) -> list[EvidenceItem]:
    """Parse an evidence inbox document. Amounts must be exact decimals."""
    rows = payload.get("evidence")
    if not isinstance(rows, list):
        raise ValueError("Evidence document requires an evidence list.")
    items: list[EvidenceItem] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each evidence row must be an object.")
        source_kind = str(row.get("source_kind") or "order")
        items.append(
            EvidenceItem(
                evidence_id=str(row["evidence_id"]),
                occurred_on=date.fromisoformat(str(row["occurred_on"])),
                amount=parse_money(row["amount"]),
                currency=str(row.get("currency") or "KRW"),
                source_kind=source_kind,  # type: ignore[arg-type]
                order_id=None if row.get("order_id") is None else str(row["order_id"]),
            )
        )
    return items


def report_to_payload(report: ReconcileReport) -> dict[str, Any]:
    """Serialize a reconcile report with amounts as strings."""
    return {
        "command": "reconcile",
        "evidence_count": report.evidence_count,
        "payment_count": report.payment_count,
        "matched": report.matched,
        "partial": report.partial,
        "unmatched": report.unmatched,
        "groups": [_group_to_payload(group) for group in report.groups],
    }


def _group_to_payload(group: MatchGroup) -> dict[str, Any]:
    return {
        "evidence_ids": list(group.evidence_ids),
        "payment_ids": list(group.payment_ids),
        "status": group.status,
        "residual": str(group.residual),
        "reason": group.reason,
        "decision": group.decision,
    }
