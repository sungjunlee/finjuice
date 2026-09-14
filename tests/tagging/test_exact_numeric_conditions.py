"""Exact Decimal numeric tagging comparisons and schema validation."""

from __future__ import annotations

from decimal import Decimal, FloatOperation, localcontext

import pytest

from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.tagging.matcher_helpers import (
    _check_greater_than,
    _check_less_than,
)
from finjuice.pipeline.tagging.models import Condition, TagRule
from finjuice.pipeline.tagging.rules import apply_tagging_rules_v3
from finjuice.pipeline.tagging.validator_schema import (
    _parse_between_range,
    _validate_condition,
)

LARGE_INT = "9007199254740993"
LARGE_INT_MINUS = "9007199254740992"
HIGH_FRAC = "0.12345678901234567890123456789"
HIGH_FRAC_BELOW = "0.12345678901234567890123456788"
NONFINITE_TEXTS = (
    "NaN",
    "sNaN",
    "Infinity",
    "-Infinity",
    "inf",
    "+inf",
    "-inf",
    "nan",
)


def _transaction(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "merchant_raw": "서울 병원",
        "memo_raw": "",
        "major_raw": "",
        "minor_raw": "",
        "amount": Decimal("-150000"),
        "type_norm": "expense",
        "account": "삼성카드",
    }
    payload.update(overrides)
    return payload


def _amount_condition(op: str, value: str) -> Condition:
    return Condition(field="amount", op=op, value=value)


def _numeric_rule(op: str = "less_than", value: str = "-100000") -> TagRule:
    return TagRule(name="numeric", tags=["match"], conditions=[_amount_condition(op, value)])


def _result(amount: object, rules: list[TagRule], **overrides: object):
    return apply_tagging_rules_v3(_transaction(amount=amount, **overrides), rules)


def _exact_amount(lexical: str) -> Decimal:
    return ExactValue.from_lexical(lexical, value_kind="money", currency="KRW").to_decimal()


class TestExactNumericMatching:
    """apply_tagging_rules_v3 must compare amounts as exact decimals."""

    def test_large_integers_beyond_float_mantissa(self) -> None:
        amount = _exact_amount(LARGE_INT)
        gt_rules = [_numeric_rule(op="greater_than", value=LARGE_INT_MINUS)]
        lt_rules = [_numeric_rule(op="less_than", value=LARGE_INT)]
        eq_gt = [_numeric_rule(op="greater_than", value=LARGE_INT)]
        between_rules = [_numeric_rule(op="between", value=f"{LARGE_INT_MINUS},{LARGE_INT}")]

        assert _result(amount, gt_rules).tags == ["match"]
        assert _result(_exact_amount(LARGE_INT_MINUS), lt_rules).tags == ["match"]
        assert _result(amount, eq_gt).tags == []
        assert _result(amount, between_rules).tags == ["match"]
        assert _result(_exact_amount(LARGE_INT_MINUS), between_rules).tags == ["match"]
        assert float(int(LARGE_INT)) == float(int(LARGE_INT_MINUS))

    def test_high_precision_fractional_threshold(self) -> None:
        amount = Decimal(HIGH_FRAC)
        gt_rules = [_numeric_rule(op="greater_than", value=HIGH_FRAC_BELOW)]
        lt_rules = [_numeric_rule(op="less_than", value=HIGH_FRAC)]
        between_rules = [_numeric_rule(op="between", value=f"{HIGH_FRAC},{HIGH_FRAC}")]

        assert _result(amount, gt_rules).tags == ["match"]
        assert _result(amount, lt_rules).tags == []
        assert _result(amount, between_rules).tags == ["match"]
        assert float(HIGH_FRAC) == float(HIGH_FRAC_BELOW)

    def test_tiny_scientific_lexeme_vs_zero_and_neighbor(self) -> None:
        amount = "1e-400"
        assert _result(amount, [_numeric_rule(op="greater_than", value="0")]).tags == ["match"]
        assert _result(amount, [_numeric_rule(op="less_than", value="2e-400")]).tags == ["match"]
        assert _result(amount, [_numeric_rule(op="less_than", value="0")]).tags == []
        assert _result(amount, [_numeric_rule(op="greater_than", value="2e-400")]).tags == []
        assert _result("0", [_numeric_rule(op="greater_than", value="0")]).tags == []

    def test_tiny_context_and_float_operation_trap(self) -> None:
        amount = _exact_amount(LARGE_INT)
        rules = [_numeric_rule(op="greater_than", value=LARGE_INT_MINUS)]
        tiny_rules = [_numeric_rule(op="less_than", value="2e-400")]
        with localcontext() as context:
            context.prec = 1
            context.traps[FloatOperation] = True
            large = apply_tagging_rules_v3(_transaction(amount=amount), rules)
            tiny = apply_tagging_rules_v3(_transaction(amount="1e-400"), tiny_rules)
        assert large.tags == ["match"]
        assert tiny.tags == ["match"]

    def test_between_includes_exact_endpoints(self) -> None:
        rules = [_numeric_rule(op="between", value="-50000,-10000")]
        assert _result(Decimal("-50000"), rules).tags == ["match"]
        assert _result(Decimal("-10000"), rules).tags == ["match"]
        assert _result(Decimal("-50000.1"), rules).tags == []
        assert _result(Decimal("-9999"), rules).tags == []

    def test_negative_amount_less_than(self) -> None:
        rules = [_numeric_rule(op="less_than", value="-100000")]
        assert _result(Decimal("-150000"), rules).tags == ["match"]
        assert _result(Decimal("-100000"), rules).tags == []
        assert _result(Decimal("-99999"), rules).tags == []

    def test_all_and_any_combined_with_text(self) -> None:
        amount = _amount_condition("less_than", "-100000")
        text = Condition(field="merchant_raw", op="contains", value="병원")
        all_rules = [TagRule(name="all", tags=["match"], conditions=[amount, text], logic="all")]
        any_rules = [TagRule(name="any", tags=["match"], conditions=[amount, text], logic="any")]

        assert _result(Decimal("-150000"), all_rules).tags == ["match"]
        assert _result(Decimal("-150000"), all_rules, merchant_raw="카페").tags == []
        assert _result(Decimal("0"), all_rules).tags == []
        assert _result(Decimal("0"), any_rules).tags == ["match"]
        assert _result(Decimal("0"), any_rules, merchant_raw="카페").tags == []

    def test_enabled_priority_dedup_and_category_unchanged(self) -> None:
        amount = _amount_condition("less_than", "-100000")
        rules = [
            TagRule(
                name="disabled",
                tags=["skip"],
                conditions=[amount],
                category="disabled-cat",
                priority=100,
                enabled=False,
            ),
            TagRule(
                name="high",
                tags=["의료", "대형지출"],
                conditions=[amount],
                category="의료비",
                priority=90,
            ),
            TagRule(
                name="low",
                tags=["대형지출", "추가"],
                conditions=[amount],
                category="other",
                priority=40,
            ),
        ]
        result = apply_tagging_rules_v3(_transaction(amount=Decimal("-150000")), rules)
        assert result.tags == ["의료", "대형지출", "추가"]
        assert result.category_rule == "의료비"
        assert result.matching_rules == ["high", "low"]

    def test_legacy_float_and_int_amounts_remain_compatible(self) -> None:
        assert _result(-150000.0, [_numeric_rule()]).tags == ["match"]
        mid = [_numeric_rule(op="between", value="-50000,-10000")]
        assert _result(-30000.0, mid).tags == ["match"]
        assert _result(2500000, [_numeric_rule(op="greater_than", value="0")]).tags == ["match"]
        assert _result(-150000, [_numeric_rule()]).tags == ["match"]

    def test_helpers_accept_normal_numeric_arguments(self) -> None:
        assert _check_less_than(10.0, "20") is True
        assert _check_less_than(20, "20") is False
        assert _check_greater_than(21, "20") is True
        assert _check_greater_than(Decimal("21"), 20) is True
        assert _check_less_than(True, "2") is False
        assert _check_greater_than(1, "inf") is False

    @pytest.mark.parametrize(
        "amount",
        [
            None,
            True,
            False,
            "abc",
            float("nan"),
            float("inf"),
            float("-inf"),
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            *NONFINITE_TEXTS,
        ],
    )
    def test_invalid_and_nonfinite_amounts_do_not_match(self, amount: object) -> None:
        assert _result(amount, [_numeric_rule(op="greater_than", value="-1")]).tags == []


class TestExactNumericSchemaValidation:
    """Numeric rule values must reject nonfinite and collapsed reversed ranges."""

    def test_reversed_large_bounds_rejected(self) -> None:
        with pytest.raises(ValueError, match="min must be <= max"):
            _validate_condition(
                "big_range",
                {"field": "amount", "op": "between", "value": f"{LARGE_INT},{LARGE_INT_MINUS}"},
                0,
            )
        with pytest.raises(ValueError, match="min must be <= max"):
            _validate_condition(
                "big_list",
                {
                    "field": "amount",
                    "op": "between",
                    "value": [int(LARGE_INT), int(LARGE_INT_MINUS)],
                },
                0,
            )

    def test_ordered_large_bounds_and_equal_endpoints_accepted(self) -> None:
        ordered = _validate_condition(
            "ok",
            {"field": "amount", "op": "between", "value": [int(LARGE_INT_MINUS), int(LARGE_INT)]},
            0,
        )
        equal = _validate_condition(
            "eq",
            {"field": "amount", "op": "between", "value": "5,5"},
            0,
        )
        assert ordered.value == f"{LARGE_INT_MINUS},{LARGE_INT}"
        assert equal.value == "5,5"
        minimum, maximum = _parse_between_range(f"{LARGE_INT},{LARGE_INT_MINUS}")
        assert minimum is not None and maximum is not None
        assert minimum > maximum
        assert float(int(LARGE_INT)) == float(int(LARGE_INT_MINUS))

    def test_scientific_list_tuple_whitespace_and_signed_zero(self) -> None:
        scientific = _validate_condition(
            "sci",
            {"field": "amount", "op": "less_than", "value": "1e-400"},
            0,
        )
        listed = _validate_condition(
            "lst",
            {"field": "amount", "op": "between", "value": [-50000, -10000]},
            0,
        )
        tupled = _validate_condition(
            "tup",
            {"field": "amount", "op": "between", "value": (-50000, -10000)},
            0,
        )
        padded = _validate_condition(
            "pad",
            {"field": "amount", "op": "greater_than", "value": "  +1.5  "},
            0,
        )
        signed_zero = _validate_condition(
            "zero",
            {"field": "amount", "op": "greater_than", "value": "-0"},
            0,
        )
        coerced = _validate_condition(
            "dec",
            {"field": "amount", "op": "less_than", "value": Decimal("1E-400")},
            0,
        )
        assert scientific.value == "1e-400"
        assert listed.value == tupled.value == "-50000,-10000"
        assert padded.value == "  +1.5  "
        assert signed_zero.value == "-0"
        assert coerced.value == "1E-400"

    @pytest.mark.parametrize("raw", NONFINITE_TEXTS)
    def test_schema_rejects_nonfinite_scalars(self, raw: str) -> None:
        with pytest.raises(ValueError, match="invalid numeric"):
            _validate_condition(
                "bad",
                {"field": "amount", "op": "less_than", "value": raw},
                0,
            )

    @pytest.mark.parametrize("raw", ["1,inf", "nan,1", "Infinity,0", "-inf,inf", "1,sNaN"])
    def test_schema_rejects_nonfinite_between(self, raw: str) -> None:
        with pytest.raises(ValueError, match="invalid 'value' for between"):
            _validate_condition(
                "bad",
                {"field": "amount", "op": "between", "value": raw},
                0,
            )

    def test_schema_rejects_nonfinite_float_and_decimal_inputs(self) -> None:
        with pytest.raises(ValueError, match="invalid numeric"):
            _validate_condition(
                "nan_float",
                {"field": "amount", "op": "greater_than", "value": float("nan")},
                0,
            )
        with pytest.raises(ValueError, match="invalid numeric"):
            _validate_condition(
                "inf_dec",
                {"field": "amount", "op": "greater_than", "value": Decimal("Infinity")},
                0,
            )
