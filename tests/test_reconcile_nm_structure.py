"""Identity and synthetic AC coverage for N:M reconcile (issue #446).

Matchers live in ``nm`` and stay identity-equal when re-exported from
``engine``. Confirm/withdraw live in ``decisions``. The SQLite sidecar stores
source/evidence relations without rewriting occurrence rows. Public CI uses
synthetic fixtures only; this module never reads a default user data directory.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from finjuice.pipeline.reconcile import (
    EvidenceItem,
    PaymentItem,
    ReconcileStore,
    confirm_match,
    ledger_cash_spend,
    reconcile,
    withdraw_match,
)
from finjuice.pipeline.reconcile import decisions as decisions_module
from finjuice.pipeline.reconcile import engine as engine_module
from finjuice.pipeline.reconcile import nm as nm_module
from finjuice.pipeline.reconcile import spend as spend_module
from finjuice.pipeline.reconcile import store as store_module

RECONCILE_DIR = Path("src/finjuice/pipeline/reconcile")
ENGINE_MODULE = "finjuice.pipeline.reconcile.engine"
NM_MODULE = "finjuice.pipeline.reconcile.nm"
DECISIONS_MODULE = "finjuice.pipeline.reconcile.decisions"
SPEND_MODULE = "finjuice.pipeline.reconcile.spend"
STORE_MODULE = "finjuice.pipeline.reconcile.store"

NM_HELPER_NAMES = (
    "_match_one_to_one",
    "_match_one_to_many",
    "_match_many_to_one",
    "_unmatched_evidence",
)
DECISION_NAMES = ("confirm_match", "withdraw_match")


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


def _import_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_nm_matchers_live_in_nm_module() -> None:
    engine_text = (RECONCILE_DIR / "engine.py").read_text(encoding="utf-8")
    nm_text = (RECONCILE_DIR / "nm.py").read_text(encoding="utf-8")

    for name in NM_HELPER_NAMES:
        assert f"def {name}" not in engine_text
        assert f"def {name}" in nm_text
        assert name in engine_text


def test_nm_matchers_reexport_from_engine() -> None:
    engine = importlib.import_module(ENGINE_MODULE)
    nm = importlib.import_module(NM_MODULE)

    for name in NM_HELPER_NAMES:
        assert getattr(engine, name) is getattr(nm, name)
        assert getattr(nm, name).__module__ == NM_MODULE
        assert getattr(engine, name).__module__ == NM_MODULE


def test_confirm_withdraw_live_in_decisions() -> None:
    engine_text = (RECONCILE_DIR / "engine.py").read_text(encoding="utf-8")
    decisions_text = (RECONCILE_DIR / "decisions.py").read_text(encoding="utf-8")

    for name in DECISION_NAMES:
        assert f"def {name}" not in engine_text
        assert f"def {name}" in decisions_text
        assert name in engine_text
        assert getattr(engine_module, name) is getattr(decisions_module, name)
        assert getattr(decisions_module, name).__module__ == DECISIONS_MODULE


def test_nm_does_not_import_engine_or_package() -> None:
    for line in _import_lines(RECONCILE_DIR / "nm.py"):
        assert "finjuice.pipeline.reconcile.engine" not in line
        assert "from finjuice.pipeline.reconcile import" not in line
    for line in _import_lines(RECONCILE_DIR / "decisions.py"):
        assert "finjuice.pipeline.reconcile.engine" not in line
        assert "finjuice.pipeline.reconcile.store" not in line
        assert "from finjuice.pipeline.reconcile import" not in line
    for line in _import_lines(RECONCILE_DIR / "spend.py"):
        assert "finjuice.pipeline.reconcile.engine" not in line
        assert "from finjuice.pipeline.reconcile import" not in line


def test_one_purchase_matches_installment_payments() -> None:
    report = reconcile(
        [_evidence("e-installment", "2024-01-10", "300000")],
        [
            _payment("p-inst-1", "2024-01-10", "-100000"),
            _payment("p-inst-2", "2024-02-10", "-100000"),
            _payment("p-inst-3", "2024-03-10", "-100000"),
        ],
        window_days=70,
    )

    assert report.matched == 1
    assert report.groups[0].reason == "installment_one_to_many"
    assert report.groups[0].payment_ids == ("p-inst-1", "p-inst-2", "p-inst-3")
    assert ledger_cash_spend(
        [
            _payment("p-inst-1", "2024-01-10", "-100000"),
            _payment("p-inst-2", "2024-02-10", "-100000"),
            _payment("p-inst-3", "2024-03-10", "-100000"),
        ],
        report.groups,
    ) == Decimal("-300000")


def test_two_orders_match_one_payment() -> None:
    payments = [_payment("p-bundle", "2024-05-02", "-30000")]
    report = reconcile(
        [
            _evidence("e-order-a", "2024-05-01", "12000"),
            _evidence("e-order-b", "2024-05-01", "18000"),
        ],
        payments,
    )

    assert report.matched == 1
    assert set(report.groups[0].evidence_ids) == {"e-order-a", "e-order-b"}
    assert report.groups[0].reason == "orders_many_to_one"
    assert ledger_cash_spend(payments, report.groups) == Decimal("-30000")


def test_refund_and_partial_matching() -> None:
    refund = reconcile(
        [_evidence("e-refund", "2024-06-01", "50000")],
        [_payment("p-refund", "2024-06-03", "50000")],
    )
    partial = reconcile(
        [_evidence("e-partial", "2024-01-10", "300000")],
        [
            _payment("p-part-1", "2024-01-10", "-100000"),
            _payment("p-part-2", "2024-02-10", "-100000"),
        ],
        window_days=70,
    )

    assert refund.groups[0].reason == "refund_or_inflow"
    assert refund.groups[0].status == "matched"
    assert partial.partial == 1
    assert partial.groups[0].residual == Decimal("100000")


def test_store_preserves_occurrence_and_does_not_duplicate(tmp_path: Path) -> None:
    store = ReconcileStore(tmp_path / "reconcile.sqlite3")
    evidence = [_evidence("e-keep", "2024-01-01", "10000")]
    payments = [_payment("p-keep", "2024-01-01", "-10000")]

    first = store.record_and_reconcile(evidence, payments)
    second = store.record_and_reconcile(
        [_evidence("e-keep", "2024-01-01", "99999")],
        [_payment("p-keep", "2024-01-01", "-1")],
    )

    assert first.groups == second.groups
    assert len(store.load_groups()) == 1
    assert store.load_evidence()[0].amount == Decimal("10000")
    assert store.load_payments()[0].amount == Decimal("-10000")


def test_confirm_and_withdraw_leave_occurrences_intact(tmp_path: Path) -> None:
    store = ReconcileStore(tmp_path / "reconcile.sqlite3")
    report = store.record_and_reconcile(
        [_evidence("e-manual", "2024-01-01", "10000")],
        [_payment("p-manual", "2024-01-01", "-10000")],
    )
    original_evidence = store.load_evidence()
    original_payments = store.load_payments()

    original_group = report.groups[0]
    confirmed = store.confirm(original_group)
    withdrawn = store.withdraw(confirmed)
    rematch = store.record_and_reconcile(
        [_evidence("e-manual", "2024-01-01", "10000")],
        [_payment("p-manual", "2024-01-01", "-10000")],
    )

    assert original_group.decision == "proposed"
    assert confirm_match(original_group).decision == "confirmed"
    assert withdraw_match(original_group).decision == "withdrawn"
    assert confirmed.decision == "confirmed"
    assert withdrawn.decision == "withdrawn"
    assert store.load_evidence() == original_evidence
    assert store.load_payments() == original_payments
    assert rematch.groups[0].decision == "withdrawn"
    assert rematch.groups[0].payment_ids == ("p-manual",)


def test_store_requires_explicit_path_and_synthetic_ids(tmp_path: Path) -> None:
    store = ReconcileStore(tmp_path / "synthetic.sqlite3")
    store.record_and_reconcile(
        [_evidence("synth-e1", "2023-02-11", "52000")],
        [],
    )

    assert store.path == (tmp_path / "synthetic.sqlite3").resolve()
    assert store.path.is_relative_to(tmp_path)
    assert store.load_groups()[0].status == "unmatched"
    assert store.load_groups()[0].reason == "missing_ledger_coverage"


def test_spend_and_store_definition_sites() -> None:
    assert spend_module.ledger_cash_spend.__module__ == SPEND_MODULE
    assert store_module.ReconcileStore.__module__ == STORE_MODULE
    assert ledger_cash_spend is spend_module.ledger_cash_spend
    assert ReconcileStore is store_module.ReconcileStore
    assert nm_module._match_one_to_many.__module__ == NM_MODULE
