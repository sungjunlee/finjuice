"""Domain records for purchase/order evidence vs ledger payments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

EvidenceSourceKind = Literal["order", "receipt", "email_export", "manual_evidence"]
MatchStatus = Literal["matched", "partial", "unmatched"]
MatchDecision = Literal["proposed", "confirmed", "withdrawn"]

LEDGER_SOURCE_KINDS = frozenset({"banksalad", "manual_ledger"})
EVIDENCE_SOURCE_KINDS = frozenset({"order", "receipt", "email_export", "manual_evidence"})


@dataclass(frozen=True)
class EvidenceItem:
    """One purchase/order/receipt occurrence. Never a ledger transaction."""

    evidence_id: str
    occurred_on: date
    amount: Decimal
    currency: str
    source_kind: EvidenceSourceKind
    order_id: str | None = None


@dataclass(frozen=True)
class PaymentItem:
    """One ledger payment occurrence (Banksalad row or equivalent)."""

    payment_id: str
    occurred_on: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class MatchGroup:
    """One N:M allocation between evidence and payments."""

    evidence_ids: tuple[str, ...]
    payment_ids: tuple[str, ...]
    status: MatchStatus
    residual: Decimal
    reason: str
    decision: MatchDecision = "proposed"


@dataclass(frozen=True)
class ReconcileReport:
    """Deterministic reconcile result. Evidence rows are never deleted."""

    groups: tuple[MatchGroup, ...]
    evidence_count: int
    payment_count: int

    @property
    def matched(self) -> int:
        return sum(1 for group in self.groups if group.status == "matched")

    @property
    def partial(self) -> int:
        return sum(1 for group in self.groups if group.status == "partial")

    @property
    def unmatched(self) -> int:
        return sum(1 for group in self.groups if group.status == "unmatched")
