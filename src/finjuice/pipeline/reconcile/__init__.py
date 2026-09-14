"""Purchase/order evidence reconciliation (issue #446).

This module matches evidence occurrences to ledger payments without treating
email/order exports as the ledger SSOT, and without deleting unmatched
evidence when a Banksalad month is missing.
"""

from finjuice.pipeline.reconcile.decisions import confirm_match, withdraw_match
from finjuice.pipeline.reconcile.engine import DEFAULT_WINDOW_DAYS, reconcile
from finjuice.pipeline.reconcile.models import (
    EvidenceItem,
    MatchGroup,
    PaymentItem,
    ReconcileReport,
)
from finjuice.pipeline.reconcile.spend import ledger_cash_spend
from finjuice.pipeline.reconcile.store import ReconcileStore

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "EvidenceItem",
    "MatchGroup",
    "PaymentItem",
    "ReconcileReport",
    "ReconcileStore",
    "confirm_match",
    "ledger_cash_spend",
    "reconcile",
    "withdraw_match",
]
