"""Exact, UUID-identified payment candidates from one canonical transaction snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from finjuice.pipeline.reconcile.models import PaymentItem
from finjuice.pipeline.reconcile.payments import payment_reference
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot, snapshot_metadata
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.transaction_completeness import (
    require_transaction_completeness,
)
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot


class RepositoryReconcileError(ValueError):
    """Static failure when canonical reconcile inputs cannot be interpreted."""


@dataclass(frozen=True)
class RepositoryPayments:
    """Detached payment candidates and their canonical source policies."""

    payments: tuple[PaymentItem, ...]
    metadata: dict[str, Any]


def read_repository_payments(
    data_dir: Path, provider: ActivationEvidenceProvider | None
) -> RepositoryPayments | None:
    """Read one authoritative revision; return None only for verified legacy authority."""
    try:
        snapshot = read_transaction_snapshot(data_dir, provider)
        return payments_from_snapshot(snapshot) if snapshot is not None else None
    except Exception:
        raise RepositoryReconcileError(
            "Canonical reconciliation payments are unavailable."
        ) from None


def payments_from_snapshot(snapshot: TransactionReadSnapshot) -> RepositoryPayments:
    """Retain every included occurrence without floats, alias merging, or config reads."""
    try:
        require_transaction_completeness(snapshot)
        rows = {row["transaction_id"]: row for row in snapshot.rows}
        if (
            len(rows) != len(snapshot.rows)
            or len(snapshot.scopes) != len(rows)
            or {scope.transaction_id for scope in snapshot.scopes} != set(rows)
        ):
            raise ValueError("Canonical payment scope evidence is incomplete.")
        payments = tuple(
            _payment(rows[scope.transaction_id])
            for scope in sorted(snapshot.scopes, key=lambda scope: scope.transaction_id)
            if scope.included
        )
        return RepositoryPayments(
            payments,
            {
                **snapshot_metadata(snapshot),
                "read_policy": "exact_payment_candidates.v1",
                "calculation_policy": "canonical_reconcile_exact.v1",
                "payment_identity_policy": "transaction_uuid.v1",
                "payment_scope_policy": "primary_and_native.v1",
                "amount_policy": "exact_decimal_tuple.v1",
                "date_policy": "legacy_iso_date_prefix.v1",
                "unknown_currency_policy": "reject",
                "unknown_date_policy": "reject",
                "payment_count": len(payments),
                "excluded_scope_count": len(rows) - len(payments),
            },
        )
    except Exception:
        raise RepositoryReconcileError(
            "Canonical reconciliation payments are unavailable."
        ) from None


def _payment(row: dict[str, Any]) -> PaymentItem:
    identity = row["transaction_id"]
    if not isinstance(identity, str) or str(UUID(identity)) != identity:
        raise ValueError("Payment identity is not a canonical UUID.")
    raw_date = row["date"]
    if not isinstance(raw_date, str) or len(raw_date) < 10:
        raise ValueError("Payment date is unavailable.")
    occurred_on = date.fromisoformat(raw_date[:10])
    if occurred_on.isoformat() != raw_date[:10]:
        raise ValueError("Payment date is invalid.")
    currency = row["currency"]
    if not isinstance(currency, str) or row["currency_unknown"] not in (False, 0):
        raise ValueError("Payment currency is unavailable.")
    # Revalidate the public writer's digit/scale/unit/lexical bounds. Calculated
    # permits missing lexical evidence; this does not change stored origin data.
    exact = ExactValue(
        row["amount_coefficient"],
        row["amount_scale"],
        row["amount_lexical"],
        "money",
        "calculated",
        currency=currency,
    )
    amount = exact.to_decimal()
    if exact.lexical is not None and amount.is_zero():
        amount = amount.copy_sign(Decimal(exact.lexical))
    raw_amount = row["amount"]
    if not isinstance(raw_amount, str):
        raise ValueError("Payment amount is not exact text.")
    displayed = Decimal(raw_amount)
    if not displayed.is_finite() or displayed != amount:
        raise ValueError("Payment amount evidence is inconsistent.")
    return PaymentItem(identity, occurred_on, amount, currency, payment_reference(row))
