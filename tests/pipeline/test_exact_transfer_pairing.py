"""Focused tests for the pure exact transfer matcher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from finjuice.pipeline.storage.sqlite import UNKNOWN_CURRENCY, ExactValue
from finjuice.pipeline.storage.sqlite.errors import ExactValueError, IdentifierError
from finjuice.pipeline.transfer.exact_pairing import (
    ExactTransferCandidate,
    pair_exact_transfer_candidates,
)

BASE_TIME = datetime(2026, 9, 9, 12, 0, 0)
UUIDS = {
    name: f"00000000-0000-4000-8000-{number:012d}"
    for name, number in {
        "a": 1,
        "b": 2,
        "c": 3,
        "d": 4,
        "e": 5,
        "f": 6,
    }.items()
}


def _candidate(
    name: str,
    lexical: str,
    *,
    at: datetime = BASE_TIME,
    currency: str | object = "KRW",
    category: str = "내계좌이체",
) -> ExactTransferCandidate:
    currency_value = currency if isinstance(currency, str) else UNKNOWN_CURRENCY
    amount = ExactValue.from_lexical(lexical, value_kind="money", currency=currency_value)
    return ExactTransferCandidate(
        transaction_id=UUIDS[name],
        datetime=at,
        amount=amount,
        account="account",
        counterparty="counterparty",
        major_category=category,
    )


def _group(left: str, right: str) -> str:
    return f"T_{min(UUIDS[left], UUIDS[right])}_{max(UUIDS[left], UUIDS[right])}"


def test_exact_pair_returns_oriented_full_id_group_and_is_input_order_independent() -> None:
    outgoing = _candidate("a", "-100.00")
    incoming = _candidate("b", "100.00", at=BASE_TIME + timedelta(minutes=1))
    original = [outgoing, incoming]

    expected = {_group("a", "b"): (UUIDS["a"], UUIDS["b"])}
    assert pair_exact_transfer_candidates(original) == expected
    assert pair_exact_transfer_candidates(reversed(original)) == expected
    assert original == [outgoing, incoming]


def test_large_integer_amounts_do_not_collapse_at_binary_float_precision() -> None:
    outgoing = _candidate("a", f"-{2**53 + 1}")
    wrong = _candidate("b", f"{2**53}", at=BASE_TIME + timedelta(seconds=1))
    exact = _candidate("c", f"{2**53 + 1}", at=BASE_TIME + timedelta(seconds=1))

    result = pair_exact_transfer_candidates([outgoing, wrong, exact])

    assert result == {_group("a", "c"): (UUIDS["a"], UUIDS["c"])}


def test_storage_scale_255_is_pairable_but_scale_256_is_rejected() -> None:
    outgoing = _candidate("a", "-1e-255")
    incoming = _candidate("b", "1e-255")

    assert pair_exact_transfer_candidates([outgoing, incoming]) == {
        _group("a", "b"): (UUIDS["a"], UUIDS["b"])
    }
    with pytest.raises(ExactValueError, match="Scale must be between"):
        ExactValue.from_lexical("1e-256", value_kind="money", currency="KRW")


def test_exact_values_ignore_ambient_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        outgoing = _candidate("a", "-123456789012345678901234567890.123456789")
        incoming = _candidate("b", "123456789012345678901234567890.123456789")

    assert pair_exact_transfer_candidates([outgoing, incoming]) == {
        _group("a", "b"): (UUIDS["a"], UUIDS["b"])
    }


def test_tolerance_accepts_exact_one_percent_but_rejects_one_step_beyond() -> None:
    exact = [_candidate("a", "-100"), _candidate("b", "99")]
    beyond = [_candidate("a", "-100"), _candidate("b", "98.99")]

    assert pair_exact_transfer_candidates(exact, amount_tolerance="0.01")
    assert pair_exact_transfer_candidates(beyond, amount_tolerance=Fraction(1, 100)) == {}


def test_zero_and_signed_zero_never_form_a_pair() -> None:
    candidates = [_candidate("a", "-0.00"), _candidate("b", "0.00")]

    assert candidates[0].amount.coefficient == "0"
    assert pair_exact_transfer_candidates(candidates) == {}


def test_unknown_or_mismatched_currency_cannot_confirm() -> None:
    unknown = [
        _candidate("a", "-100", currency=UNKNOWN_CURRENCY),
        _candidate("b", "100", currency=UNKNOWN_CURRENCY),
    ]
    mismatched = [_candidate("a", "-100", currency="KRW"), _candidate("b", "100", currency="USD")]

    assert pair_exact_transfer_candidates(unknown) == {}
    assert pair_exact_transfer_candidates(mismatched) == {}


def test_same_sign_or_different_category_cannot_pair() -> None:
    same_sign = [_candidate("a", "-100"), _candidate("b", "-100")]
    different_category = [
        _candidate("a", "-100", category="내계좌이체"),
        _candidate("b", "100", category="카드결제"),
    ]

    assert pair_exact_transfer_candidates(same_sign) == {}
    assert pair_exact_transfer_candidates(different_category) == {}


def test_time_window_uses_exact_microsecond_boundary() -> None:
    within = [
        _candidate("a", "-100"),
        _candidate("b", "100", at=BASE_TIME + timedelta(minutes=5)),
    ]
    outside = [
        _candidate("a", "-100"),
        _candidate("b", "100", at=BASE_TIME + timedelta(minutes=5, microseconds=1)),
    ]

    assert pair_exact_transfer_candidates(within)
    assert pair_exact_transfer_candidates(outside) == {}


def test_reversed_ties_use_stable_candidate_keys_and_greedy_removal() -> None:
    candidates = [
        _candidate("a", "-100"),
        _candidate("b", "-100"),
        _candidate("c", "100"),
        _candidate("d", "100"),
    ]

    expected = {
        _group("a", "c"): (UUIDS["a"], UUIDS["c"]),
        _group("b", "d"): (UUIDS["b"], UUIDS["d"]),
    }
    assert pair_exact_transfer_candidates(candidates) == expected
    assert pair_exact_transfer_candidates(reversed(candidates)) == expected


def test_duplicate_or_invalid_stable_ids_fail_closed() -> None:
    first = _candidate("a", "-100")
    duplicate = ExactTransferCandidate(
        transaction_id=first.transaction_id,
        datetime=BASE_TIME,
        amount=ExactValue.from_lexical("100", value_kind="money", currency="KRW"),
        account="account",
        counterparty="counterparty",
        major_category="내계좌이체",
    )
    with pytest.raises(ValueError, match="unique"):
        pair_exact_transfer_candidates([first, duplicate])

    with pytest.raises(IdentifierError, match="canonical UUID"):
        ExactTransferCandidate(
            transaction_id="not-an-id",
            datetime=BASE_TIME,
            amount=ExactValue.from_lexical("1", value_kind="money", currency="KRW"),
            account="account",
            counterparty="counterparty",
            major_category="내계좌이체",
        )


@pytest.mark.parametrize(
    "tolerance",
    [
        True,
        False,
        0.01,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e1000000"),
        "-0.01",
        "1.01",
    ],
)
def test_invalid_tolerance_is_rejected(tolerance: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        pair_exact_transfer_candidates([], amount_tolerance=tolerance)  # type: ignore[arg-type]


@pytest.mark.parametrize("window", [True, False, -1, 1.5])
def test_invalid_time_window_is_rejected(window: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        pair_exact_transfer_candidates([], time_window_minutes=window)  # type: ignore[arg-type]


def test_mixed_naive_and_aware_timestamps_are_rejected() -> None:
    candidates = [
        _candidate("a", "-100"),
        _candidate("b", "100", at=BASE_TIME.replace(tzinfo=timezone.utc)),
    ]

    with pytest.raises(ValueError, match="mixed naive"):
        pair_exact_transfer_candidates(candidates)


def test_aware_dst_fold_uses_actual_utc_distance() -> None:
    from zoneinfo import ZoneInfo

    daylight = ZoneInfo("America/New_York")
    fold_zero = datetime(2026, 11, 1, 1, 30, tzinfo=daylight, fold=0)
    fold_one = datetime(2026, 11, 1, 1, 30, tzinfo=daylight, fold=1)
    candidates = [_candidate("a", "-100", at=fold_zero), _candidate("b", "100", at=fold_one)]

    assert pair_exact_transfer_candidates(candidates) == {}


def test_aware_offsets_use_actual_instant_and_microsecond_boundary() -> None:
    plus_nine = timezone(timedelta(hours=9))
    utc = timezone.utc
    same_instant = [
        _candidate("a", "-100", at=datetime(2026, 9, 9, 12, 0, tzinfo=plus_nine)),
        _candidate("b", "100", at=datetime(2026, 9, 9, 3, 0, tzinfo=utc)),
    ]
    boundary = [
        _candidate("a", "-100", at=datetime(2026, 9, 9, 12, 0, tzinfo=plus_nine)),
        _candidate(
            "b",
            "100",
            at=datetime(2026, 9, 9, 3, 5, microsecond=1, tzinfo=utc),
        ),
    ]

    assert pair_exact_transfer_candidates(same_instant)
    assert pair_exact_transfer_candidates(boundary) == {}
    assert pair_exact_transfer_candidates(reversed(same_instant)) == pair_exact_transfer_candidates(
        same_instant
    )


def test_aware_utc_normalization_overflow_fails_closed() -> None:
    overflowing = datetime.min.replace(tzinfo=timezone(timedelta(hours=14)))

    with pytest.raises(ValueError, match="UTC"):
        pair_exact_transfer_candidates([_candidate("a", "-100", at=overflowing)])


def test_candidate_is_frozen_and_repeated_calls_are_idempotent() -> None:
    candidates = [_candidate("a", "-100"), _candidate("b", "100")]
    before = tuple(candidates)
    expected = pair_exact_transfer_candidates(candidates)

    with pytest.raises(AttributeError):
        candidates[0].account = "changed"  # type: ignore[misc]

    assert pair_exact_transfer_candidates(candidates) == expected
    assert tuple(candidates) == before
