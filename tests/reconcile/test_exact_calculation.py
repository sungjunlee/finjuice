"""Exact canonical matching is independent of process decimal settings."""

from datetime import date
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from finjuice.pipeline.reconcile.exact_calculation import reconcile_exact
from finjuice.pipeline.reconcile.models import EvidenceItem, PaymentItem

DAY = date(2026, 1, 1)


def _e(value: str, identifier: str = "e") -> EvidenceItem:
    return EvidenceItem(identifier, DAY, Decimal(value), "KRW", "order")


def _p(value: str, identifier: str = "p", currency: str = "KRW") -> PaymentItem:
    return PaymentItem(identifier, DAY, Decimal(value), currency)


def test_exact_sum_under_hostile_context_and_restore() -> None:
    evidence = [_e("12345678901234567890123456789.015")]
    payments = [_p("-12345678901234567890123456789.010", "a"), _p("-0.005", "b")]
    with localcontext() as context:
        context.prec, context.Emax, context.Emin, context.clamp = 3, 9, -9, 1
        context.traps[Inexact] = context.traps[Rounded] = True
        result = reconcile_exact(evidence, payments)
        assert result.matched == 1 and result.groups[0].residual == Decimal(0)
        assert context.prec == 3 and context.clamp == 1


def test_partial_refund_currency_and_empty() -> None:
    partial = reconcile_exact([_e("10.015")], [_p("-5.008")])
    assert partial.partial == 1 and partial.groups[0].residual == Decimal("5.007")
    assert reconcile_exact([_e("1.001")], [_p("1.001")]).groups[0].reason == "refund_or_inflow"
    assert reconcile_exact([_e("1")], [_p("-1", currency="USD")]).unmatched == 1
    assert reconcile_exact([], []).groups == ()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e-256", "1e100000"])
def test_unsupported_operands_fail_statically(value: str) -> None:
    with pytest.raises(ValueError, match="supported exact input or calculation limits"):
        reconcile_exact([_e(value)], [])


def test_large_coefficient_supported_without_float_conversion() -> None:
    value = "9" * 100_000
    assert reconcile_exact([_e(value)], [_p("-" + value)]).matched == 1
    with pytest.raises(ValueError):
        reconcile_exact([_e(value + "9")], [])


def test_uncapped_many_to_one_search_budget_rejected() -> None:
    evidence = [_e(str((200, 202, 205)[index % 3]), str(index)) for index in range(100)]
    with pytest.raises(ValueError, match="calculation limits"):
        reconcile_exact(evidence, [_p("-1001")])


def test_input_and_pair_budget_rejected() -> None:
    with pytest.raises(ValueError):
        reconcile_exact([_e("1")] * 10_001, [])
    with pytest.raises(ValueError):
        reconcile_exact([_e("1")] * 1001, [_p("-1")] * 1000)


def test_precision_weighted_budget_rejects_large_search() -> None:
    value = "1001" + "0" * 995 + "1"
    evidence = [_e(value, str(index)) for index in range(20)]
    payments = [
        _p("-" + str((200, 202, 205)[index % 3]) + "0" * 996, str(index)) for index in range(16)
    ]
    with pytest.raises(ValueError, match="calculation limits"):
        reconcile_exact(evidence, payments)


def test_scale_boundary_and_ambient_float_trap() -> None:
    from decimal import FloatOperation

    value = "0." + "0" * 254 + "1"
    with localcontext() as context:
        context.traps[FloatOperation] = True
        context.prec = 2
        assert reconcile_exact([_e(value)], [_p("-" + value)]).matched == 1


def test_ordinary_hundred_exact_matches_are_not_rejected() -> None:
    evidence = [_e("100.01", str(index)) for index in range(100)]
    payments = [_p("-100.01", str(index)) for index in range(100)]
    assert reconcile_exact(evidence, payments).matched == 100


def test_default_context_mutation_does_not_affect_calculation() -> None:
    from decimal import ROUND_UP, DefaultContext

    original = DefaultContext.copy()
    try:
        DefaultContext.prec = 1
        DefaultContext.rounding = ROUND_UP
        DefaultContext.Emax, DefaultContext.Emin = 1, -1
        DefaultContext.clamp, DefaultContext.capitals = 1, 0
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
            DefaultContext.flags[signal] = True
        result = reconcile_exact([_e("10000.015")], [_p("-5000.008")])
        assert result.groups[0].residual == Decimal("5000.007")
    finally:
        for attribute in ("prec", "rounding", "Emax", "Emin", "clamp", "capitals"):
            setattr(DefaultContext, attribute, getattr(original, attribute))
        DefaultContext.traps = original.traps.copy()
        DefaultContext.flags = original.flags.copy()


def test_fifty_orders_match_twenty_five_payments_before_fuel_exhaustion() -> None:
    evidence = [_e("1", str(index)) for index in range(50)]
    payments = [_p("-2", str(index)) for index in range(25)]
    result = reconcile_exact(evidence, payments)
    assert result.matched == 25 and result.unmatched == 0


def test_actual_work_meter_and_nested_context_restore() -> None:
    from finjuice.pipeline.reconcile.engine import reconcile, reconciliation_work_meter

    charged = []
    with reconciliation_work_meter(charged.append):
        assert reconcile_exact([_e("1")], [_p("-1")]).matched == 1
        assert charged == []
        assert reconcile([_e("1")], [_p("-1")]).matched == 1
        assert charged and all(units > 0 for units in charged)


def test_budget_exception_restores_meter_and_decimal_context(monkeypatch) -> None:
    from finjuice.pipeline.reconcile import exact_calculation
    from finjuice.pipeline.reconcile.engine import reconcile

    monkeypatch.setattr(exact_calculation, "MAX_WORK_UNITS", 1)
    with localcontext() as context:
        context.prec = 3
        with pytest.raises(ValueError):
            reconcile_exact([_e("1")], [_p("-1")])
        assert context.prec == 3
    assert reconcile([_e("1")], [_p("-1")]).matched == 1


@pytest.mark.parametrize(
    "exact_count,leftovers,payment_count", [(30, 20, 5), (10, 24, 3), (40, 25, 8)]
)
def test_ordinary_impossible_leftovers_are_pruned(exact_count, leftovers, payment_count) -> None:
    from finjuice.pipeline.reconcile.engine import reconcile

    evidence = [_e(str(3000 + i), f"exact{i}") for i in range(exact_count)]
    evidence += [_e("7", f"left{i}") for i in range(leftovers)]
    payments = [_p(str(-(3000 + i)), f"exact{i}") for i in range(exact_count)]
    payments += [_p("-13", f"left{i}") for i in range(payment_count)]
    expected = reconcile(evidence, payments)
    assert reconcile_exact(evidence, payments) == expected
    assert expected.matched == exact_count and expected.unmatched == leftovers


def test_random_small_first_choice_and_sign_currency_parity() -> None:
    import random
    from dataclasses import replace
    from datetime import timedelta

    from finjuice.pipeline.reconcile.engine import reconcile

    randomizer = random.Random(8394)
    for _ in range(80):
        evidence = [
            replace(
                _e(str(randomizer.randint(-5, 8)), str(i)),
                occurred_on=DAY + timedelta(days=randomizer.randrange(20)),
                currency=randomizer.choice(["KRW", "USD"]),
            )
            for i in range(7)
        ]
        payments = [
            replace(
                _p(str(randomizer.randint(-12, 8)), str(i)),
                occurred_on=DAY + timedelta(days=randomizer.randrange(20)),
                currency=randomizer.choice(["KRW", "USD"]),
            )
            for i in range(5)
        ]
        assert reconcile_exact(evidence, payments) == reconcile(evidence, payments)


def test_even_leftovers_cannot_match_odd_target() -> None:
    evidence = [_e(str(20 + 2 * (index % 2)), str(index)) for index in range(100)]
    report = reconcile_exact(evidence, [_p("-101", str(index)) for index in range(3)])
    assert report.unmatched == 100 and report.matched == 0


def test_fractional_gcd_and_zero_prune_preserve_feasible_order() -> None:
    from finjuice.pipeline.reconcile.engine import reconcile

    evidence = [_e("0.02", "a"), _e("0.04", "b"), _e("99", "c"), _e("0", "d")]
    for target in ("-0.03", "-0.06", "0"):
        payments = [_p(target)]
        assert reconcile_exact(evidence, payments) == reconcile(evidence, payments)


@pytest.mark.parametrize(
    "unit,total",
    [
        ("0." + "0" * 254 + "1", "0." + "0" * 254 + "2"),
        ("1" + "0" * 99_999, "2" + "0" * 99_999),
    ],
)
def test_gcd_conversion_supports_extreme_exact_two_to_one(unit: str, total: str) -> None:
    result = reconcile_exact([_e(unit, "a"), _e(unit, "b")], [_p("-" + total)])
    assert result.matched == 1
    assert result.groups[0].evidence_ids == ("a", "b")
    assert result.groups[0].reason == "orders_many_to_one"


@pytest.mark.parametrize("leftovers", [9, 24])
def test_small_payments_cannot_reach_exact_or_partial_target(leftovers: int) -> None:
    from finjuice.pipeline.reconcile.engine import reconcile

    evidence = [_e(str(3000 + i), str(i)) for i in range(30)]
    evidence += [_e("100", f"left{i}") for i in range(leftovers)]
    payments = [_p(str(-(3000 + i)), str(i)) for i in range(30)]
    payments += [_p("-1", f"left{i}") for i in range(16)]
    result = reconcile_exact(evidence, payments)
    assert result == reconcile(evidence, payments)
    assert result.matched == 30 and result.unmatched == leftovers


@pytest.mark.parametrize("payment", ["-4.999", "-5", "-5.001", "0", "5"])
def test_partial_half_boundary_and_sign_parity(payment: str) -> None:
    from finjuice.pipeline.reconcile.engine import reconcile

    evidence, payments = [_e("10")], [_p(payment, "a"), _p("0", "b")]
    assert reconcile_exact(evidence, payments) == reconcile(evidence, payments)


@pytest.mark.parametrize(
    "unit,total",
    [("0." + "0" * 254 + "1", "0." + "0" * 254 + "2"), ("1" + "0" * 99999, "2" + "0" * 99999)],
)
def test_payment_bounds_exact_extreme_one_to_two(unit: str, total: str) -> None:
    report = reconcile_exact([_e(total)], [_p("-" + unit, "a"), _p("-" + unit, "b")])
    assert report.matched == 1 and report.groups[0].reason == "installment_one_to_many"
