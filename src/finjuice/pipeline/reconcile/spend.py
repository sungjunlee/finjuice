"""Cash spend from ledger payments, never from evidence amounts."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from finjuice.pipeline.reconcile.models import MatchGroup, PaymentItem

_ZERO = Decimal("0")


def ledger_cash_spend(
    payments: Sequence[PaymentItem],
    groups: Sequence[MatchGroup] = (),
) -> Decimal:
    """Sum each ledger payment once. Evidence/order amounts are never added.

    Matched installment or multi-order groups therefore cannot double-count a
    purchase amount on top of the card/bank rows that settle it. Unlinked
    payments still count. Unmatched evidence is outstanding, not cash.
    """
    payment_map = {item.payment_id: item for item in payments}
    counted: set[str] = set()
    total = _ZERO
    for group in groups:
        for payment_id in group.payment_ids:
            if payment_id in counted:
                continue
            counted.add(payment_id)
            payment = payment_map.get(payment_id)
            if payment is not None:
                total += payment.amount
    for payment in payments:
        if payment.payment_id in counted:
            continue
        counted.add(payment.payment_id)
        total += payment.amount
    return total
