"""Asset arithmetic stays exact under a deliberately hostile decimal context."""

from datetime import date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from finjuice.pipeline.assets.aggregation import sum_contribution, valuation_change_total
from finjuice.pipeline.assets.models import (
    AggregationLine,
    EvaluationQuery,
    FxBasis,
    Measure,
    MoneyAmount,
    Observation,
    ObservationLifecycle,
    ObservationSubject,
    ObservationTime,
    Source,
)
from finjuice.pipeline.assets.money import (
    exact_add,
    exact_multiply,
    exact_subtract,
    parse_decimal,
    valued_amount,
)


def _valuation(identifier: str, amount: Decimal, day: int) -> Observation:
    return Observation(
        identifier,
        ObservationSubject("account"),
        Measure("valuation", MoneyAmount(amount, "KRW")),
        Source("institution_export"),
        ObservationTime(date(2026, 9, day), datetime(2026, 9, day)),
        ObservationLifecycle("complete", "confirmed"),
    )


def test_long_exact_fx_sums_and_valuation_delta_ignore_context() -> None:
    integer = "123456789012345678901234567890123456789012345678901234567890123456"
    amount = Decimal(integer + ".123456789")
    expected_product = Decimal(str(int(integer + "123456789") * 12345) + "e-13")
    measure = Measure(
        "valuation",
        MoneyAmount(amount, "USD"),
        fx=FxBasis("KRW", Decimal("1.2345"), date(2026, 9, 1), "synthetic"),
    )
    previous = _valuation("previous", amount, 1)
    current = _valuation("current", Decimal(integer + ".1234567901"), 2)
    assert current.measure.amount is not None
    with localcontext() as context:
        context.prec = 3
        context.Emax = 5
        context.Emin = -5
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        valued = valued_amount(measure, "KRW")
        assert valued is not None and valued.amount == expected_product
        assert exact_subtract(current.measure.amount.amount, amount) == Decimal("0.0000000011")
        assert exact_add(amount, Decimal("0.0000000011")) == current.measure.amount.amount
        lines = (
            AggregationLine("a", "valuation", None, valued, "included"),
            AggregationLine(
                "b",
                "valuation",
                None,
                MoneyAmount(expected_product.copy_negate(), "KRW"),
                "included",
            ),
            AggregationLine(
                "c", "balance", None, MoneyAmount(Decimal("0.00001"), "KRW"), "included"
            ),
        )
        assert sum_contribution(lines, "included") == Decimal("0.00001")
        assert valuation_change_total(
            (previous, current), (current,), EvaluationQuery(date(2026, 9, 2), "KRW")
        ) == Decimal("0.0000000011")


@pytest.mark.parametrize(
    "value",
    [float("nan"), 1.5, True, "NaN", "sNaN", "Infinity", "-Infinity", Decimal("NaN")],
)
def test_nonfinite_and_inexact_inputs_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        parse_decimal(value)
    with pytest.raises(ValueError):
        exact_multiply(Decimal("1"), value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        valued_amount(Measure("balance", MoneyAmount(value, "KRW")), "KRW")  # type: ignore[arg-type]


def test_exact_value_bounds_and_large_coefficients() -> None:
    # Above Python's default integer-to-string limit, but inside ExactValue's bound.
    huge = Decimal("1" + "0" * 5000)
    assert parse_decimal(10**5000) == huge
    assert exact_add(huge, Decimal("1")) == Decimal("1" + "0" * 4999 + "1")
    assert exact_multiply(Decimal("1e-255"), Decimal("1")) == Decimal("1e-255")
    for value in ("1e-256", "1e100000"):
        with pytest.raises(ValueError):
            parse_decimal(value)
    with pytest.raises(ValueError):
        exact_multiply(Decimal("1e-255"), Decimal("0.1"))
