"""Synthetic tests for evidence reconciliation (#446)."""

from datetime import date
from decimal import Decimal

import pytest

from finjuice.pipeline.reconcile import EvidenceItem, MatchGroup, PaymentItem, reconcile


def _evidence(
    evidence_id: str,
    day: str,
    amount: str,
    *,
    source_kind: str = "order",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        occurred_on=date.fromisoformat(day),
        amount=Decimal(amount),
        currency="KRW",
        source_kind=source_kind,  # type: ignore[arg-type]
        order_id=evidence_id,
    )


def _payment(payment_id: str, day: str, amount: str) -> PaymentItem:
    return PaymentItem(
        payment_id=payment_id,
        occurred_on=date.fromisoformat(day),
        amount=Decimal(amount),
        currency="KRW",
    )


def test_missing_ledger_keeps_unmatched_evidence() -> None:
    report = reconcile([_evidence("e1", "2023-02-11", "52000")], [])

    assert report.unmatched == 1
    assert report.groups[0].reason == "missing_ledger_coverage"
    assert report.groups[0].payment_ids == ()


def test_later_ledger_rows_rematch_same_evidence_id() -> None:
    evidence = [_evidence("e1", "2023-02-11", "52000")]
    empty = reconcile(evidence, [])
    filled = reconcile(evidence, [_payment("p1", "2023-02-12", "-52000")])

    assert empty.unmatched == 1
    assert filled.matched == 1
    assert filled.groups[0].evidence_ids == ("e1",)
    assert filled.groups[0].payment_ids == ("p1",)


def test_one_purchase_matches_installment_payments() -> None:
    report = reconcile(
        [_evidence("e1", "2024-01-10", "300000")],
        [
            _payment("p1", "2024-01-10", "-100000"),
            _payment("p2", "2024-02-10", "-100000"),
            _payment("p3", "2024-03-10", "-100000"),
        ],
        window_days=70,
    )

    assert report.matched == 1
    assert report.groups[0].reason == "installment_one_to_many"
    assert report.groups[0].payment_ids == ("p1", "p2", "p3")


def test_two_orders_match_one_payment() -> None:
    report = reconcile(
        [_evidence("e1", "2024-05-01", "12000"), _evidence("e2", "2024-05-01", "18000")],
        [_payment("p1", "2024-05-02", "-30000")],
    )

    assert report.matched == 1
    assert set(report.groups[0].evidence_ids) == {"e1", "e2"}
    assert report.groups[0].reason == "orders_many_to_one"


def test_partial_installment_keeps_residual() -> None:
    report = reconcile(
        [_evidence("e1", "2024-01-10", "300000")],
        [_payment("p1", "2024-01-10", "-100000"), _payment("p2", "2024-02-10", "-100000")],
        window_days=70,
    )

    assert report.partial == 1
    assert report.groups[0].residual == Decimal("100000")
    assert report.groups[0].status == "partial"


def test_unrelated_same_day_spend_does_not_greedy_partial() -> None:
    """A much larger evidence amount must stay unmatched, not eat nearby spend."""
    report = reconcile(
        [_evidence("e1", "2024-08-15", "424242421")],
        [_payment("p1", "2024-08-15", "-5000"), _payment("p2", "2024-08-15", "-7000")],
    )

    assert report.unmatched == 1
    assert report.partial == 0
    assert report.groups[0].payment_ids == ()
    assert report.groups[0].reason == "missing_ledger_coverage"


def test_busy_window_stays_unmatched_and_bounded() -> None:
    """Many in-window payments must not enumerate C(n,5) or attach as partial."""
    payments = [_payment(f"p{index}", "2024-08-15", "-5000") for index in range(80)]
    report = reconcile([_evidence("e1", "2024-08-15", "424242421")], payments)

    assert report.unmatched == 1
    assert report.partial == 0
    assert report.groups[0].payment_ids == ()


def test_installment_still_matches_among_other_small_payments() -> None:
    extras = [_payment(f"x{index}", "2024-01-10", "-5000") for index in range(20)]
    report = reconcile(
        [_evidence("e1", "2024-01-10", "300000")],
        [
            *extras,
            _payment("p1", "2024-01-10", "-100000"),
            _payment("p2", "2024-02-10", "-100000"),
            _payment("p3", "2024-03-10", "-100000"),
        ],
        window_days=70,
    )

    assert report.matched == 1
    assert report.groups[0].reason == "installment_one_to_many"
    assert set(report.groups[0].payment_ids) == {"p1", "p2", "p3"}


def test_refund_inflow_matches_purchase_evidence() -> None:
    report = reconcile(
        [_evidence("e1", "2024-06-01", "50000")],
        [_payment("p1", "2024-06-03", "50000")],
    )

    assert report.matched == 1
    assert report.groups[0].reason == "refund_or_inflow"


def test_confirmed_group_is_not_overwritten() -> None:
    preserved = MatchGroup(
        evidence_ids=("e1",),
        payment_ids=("p-old",),
        status="matched",
        residual=Decimal("0"),
        reason="manual",
        decision="confirmed",
    )
    report = reconcile(
        [_evidence("e1", "2024-01-01", "10000")],
        [_payment("p-new", "2024-01-01", "-10000")],
        preserved=[preserved],
    )

    assert report.groups[0] == preserved
    assert report.matched == 1


def test_rerun_does_not_duplicate_groups() -> None:
    evidence = [_evidence("e1", "2024-01-01", "10000")]
    payments = [_payment("p1", "2024-01-01", "-10000")]
    first = reconcile(evidence, payments)
    second = reconcile(evidence, payments)

    assert first.groups == second.groups
    assert len(second.groups) == 1


def test_email_export_is_evidence_not_ledger() -> None:
    report = reconcile(
        [_evidence("e1", "2023-02-11", "25900", source_kind="email_export")],
        [],
    )

    assert report.unmatched == 1
    with pytest.raises(ValueError, match="Ledger sources"):
        reconcile(
            [
                EvidenceItem(
                    evidence_id="bad",
                    occurred_on=date(2023, 2, 11),
                    amount=Decimal("1000"),
                    currency="KRW",
                    source_kind="banksalad",  # type: ignore[arg-type]
                )
            ],
            [],
        )
