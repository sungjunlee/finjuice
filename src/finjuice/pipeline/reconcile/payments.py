"""Load ledger payments for reconcile without treating evidence as SSOT."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from finjuice.pipeline.export.aggregations import load_transactions
from finjuice.pipeline.reconcile.models import PaymentItem
from finjuice.pipeline.reconcile.money import parse_money


def _ledger_amount(value: object) -> object:
    """Coerce CSV numeric amounts without accepting float in evidence JSON."""
    if isinstance(value, float):
        return format(value, ".2f")
    return value


def payments_from_ledger(csv_base_dir: Path) -> list[PaymentItem]:
    """Read current CSV partitions as payment candidates. Empty if none exist."""
    if not csv_base_dir.exists():
        return []
    frame = load_transactions(csv_base_dir)
    if frame.is_empty():
        return []
    payments: list[PaymentItem] = []
    for row in frame.iter_rows(named=True):
        payment_id = str(row.get("row_hash") or "")
        raw_date = str(row.get("date") or "")
        if not payment_id or not raw_date:
            continue
        payments.append(
            PaymentItem(
                payment_id=payment_id,
                occurred_on=date.fromisoformat(raw_date[:10]),
                amount=parse_money(_ledger_amount(row.get("amount") or "0")),
                currency=str(row.get("currency") or "KRW"),
            )
        )
    return payments
