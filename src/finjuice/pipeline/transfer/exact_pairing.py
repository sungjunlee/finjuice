"""Pure, exact-value transfer candidate pairing.

The legacy transfer detector operates on CSV rows and binary floating point
amounts.  This module is deliberately narrower: callers provide immutable
typed candidates backed by :class:`~finjuice.pipeline.storage.sqlite.exact.ExactValue`
and receive only candidate relations.  It does not claim account ownership or
write any transaction state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Final, Iterable, TypeAlias

from finjuice.pipeline.constants import DEFAULT_TRANSFER_TIME_WINDOW_MINUTES
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

ExactTolerance: TypeAlias = Decimal | str | Fraction | int
CandidateOrderKey: TypeAlias = tuple[datetime, int, Fraction, str, str, str, str, str]
PairOrderKey: TypeAlias = tuple[
    Fraction,
    int,
    datetime,
    datetime,
    CandidateOrderKey,
    CandidateOrderKey,
]

DEFAULT_EXACT_TRANSFER_TOLERANCE: Final[Decimal] = Decimal("0.01")
DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES: Final[int] = DEFAULT_TRANSFER_TIME_WINDOW_MINUTES
_MICROSECONDS_PER_MINUTE: Final[int] = 60 * 1_000_000
_MICROSECONDS_PER_SECOND: Final[int] = 1_000_000
_SECONDS_PER_DAY: Final[int] = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ExactTransferCandidate:
    """An immutable transaction candidate with authoritative exact money."""

    transaction_id: str
    datetime: datetime
    amount: ExactValue
    account: str
    counterparty: str
    major_category: str

    def __post_init__(self) -> None:
        """Validate the candidate boundary without coercing caller values."""
        validate_entity_id(self.transaction_id)
        if not isinstance(self.datetime, datetime):
            raise TypeError("datetime must be a datetime instance")
        if not isinstance(self.amount, ExactValue):
            raise TypeError("amount must be an ExactValue")
        if self.amount.value_kind != "money":
            raise ValueError("amount must be an ExactValue money value")
        for field_name in ("account", "counterparty", "major_category"):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")


@dataclass(frozen=True, slots=True)
class _ExactPair:
    """A valid, scored pair before greedy acceptance."""

    outgoing: ExactTransferCandidate
    incoming: ExactTransferCandidate
    ratio: Fraction
    time_distance_microseconds: int


def _decimal_fraction(value: Decimal) -> Fraction:
    """Convert a finite Decimal to a Fraction without decimal arithmetic."""
    if not value.is_finite():
        raise ValueError("amount_tolerance must be finite")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("amount_tolerance exponent must be finite")
    numerator = int("".join(str(digit) for digit in digits) or "0")
    if sign:
        numerator = -numerator
    if exponent >= 0:
        numerator *= 10**exponent
        return Fraction(numerator, 1)
    return Fraction(numerator, 10 ** (-exponent))


def _validate_decimal_tolerance_bounds(value: Decimal) -> None:
    """Check finite Decimal bounds before constructing a potentially huge Fraction."""
    if not value.is_finite():
        raise ValueError("amount_tolerance must be finite")
    if value < 0 or value > 1:
        raise ValueError("amount_tolerance must be between 0 and 1")


def _parse_tolerance(value: ExactTolerance) -> Fraction:
    """Parse the tolerance as an exact rational in the closed unit interval."""
    if isinstance(value, bool):
        raise TypeError("amount_tolerance must be an exact decimal or Fraction")
    if isinstance(value, Fraction):
        parsed = value
    elif isinstance(value, Decimal):
        _validate_decimal_tolerance_bounds(value)
        parsed = _decimal_fraction(value)
    elif isinstance(value, str):
        try:
            decimal_value = Decimal(value)
        except ArithmeticError as exc:
            raise ValueError("amount_tolerance must be a finite decimal") from exc
        _validate_decimal_tolerance_bounds(decimal_value)
        parsed = _decimal_fraction(decimal_value)
    elif isinstance(value, int):
        parsed = Fraction(value, 1)
    else:
        raise TypeError("amount_tolerance must be a Decimal, string, or Fraction")
    if parsed < 0 or parsed > 1:
        raise ValueError("amount_tolerance must be between 0 and 1")
    return parsed


def _parse_time_window(minutes: int) -> int:
    """Return a non-negative minute window in integer microseconds."""
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise TypeError("time_window_minutes must be a non-negative integer")
    if minutes < 0:
        raise ValueError("time_window_minutes must be non-negative")
    return minutes * _MICROSECONDS_PER_MINUTE


def _datetime_is_aware(value: datetime) -> bool:
    """Return timezone awareness using the datetime contract, without guessing."""
    return value.tzinfo is not None and value.utcoffset() is not None


def _comparison_datetime(value: datetime) -> datetime:
    """Return a UTC comparison value for aware datetimes, failing closed on overflow."""
    if not _datetime_is_aware(value):
        return value
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValueError("timezone-aware datetime cannot be normalized to UTC") from exc


def _validate_input(candidates: tuple[ExactTransferCandidate, ...]) -> None:
    """Reject duplicate IDs and mixed naive/aware timestamp input."""
    seen_ids: set[str] = set()
    awareness: bool | None = None
    for candidate in candidates:
        if not isinstance(candidate, ExactTransferCandidate):
            raise TypeError("transactions must contain ExactTransferCandidate values")
        if candidate.transaction_id in seen_ids:
            raise ValueError("transaction_id values must be unique")
        seen_ids.add(candidate.transaction_id)
        candidate_awareness = _datetime_is_aware(candidate.datetime)
        if awareness is None:
            awareness = candidate_awareness
        elif awareness != candidate_awareness:
            raise ValueError("mixed naive and timezone-aware datetimes are not supported")
        if candidate_awareness:
            _comparison_datetime(candidate.datetime)


def _amount_fraction(value: ExactValue) -> Fraction:
    """Represent canonical coefficient/scale as an exact rational."""
    return Fraction(int(value.coefficient), 10**value.scale)


def _candidate_sign(value: ExactValue) -> int:
    """Return -1, 0, or 1 from the canonical coefficient text."""
    if value.coefficient == "0":
        return 0
    return -1 if value.coefficient.startswith("-") else 1


def _time_distance_microseconds(left: datetime, right: datetime) -> int:
    """Compute a timedelta distance using only integer fields."""
    delta = abs(_comparison_datetime(right) - _comparison_datetime(left))
    return (
        delta.days * _SECONDS_PER_DAY + delta.seconds
    ) * _MICROSECONDS_PER_SECOND + delta.microseconds


def _same_known_currency(left: ExactValue, right: ExactValue) -> bool:
    """Return whether both exact money values carry the same known currency."""
    return (
        not left.currency_unknown
        and not right.currency_unknown
        and left.currency is not None
        and left.currency == right.currency
    )


def _relative_mismatch(left: ExactValue, right: ExactValue) -> Fraction | None:
    """Return an exact relative mismatch, or ``None`` for zero amounts."""
    left_abs = abs(_amount_fraction(left))
    right_abs = abs(_amount_fraction(right))
    largest = max(left_abs, right_abs)
    if largest == 0:
        return None
    return abs(left_abs - right_abs) / largest


def _candidate_order_key(
    candidate: ExactTransferCandidate,
) -> CandidateOrderKey:
    """Return the total candidate order used for deterministic tie-breaking."""
    amount = _amount_fraction(candidate.amount)
    sign = _candidate_sign(candidate.amount)
    sign_rank = 0 if sign < 0 else 1 if sign > 0 else 2
    return (
        _comparison_datetime(candidate.datetime),
        sign_rank,
        abs(amount),
        candidate.amount.currency or "",
        candidate.major_category,
        candidate.account,
        candidate.counterparty,
        candidate.transaction_id,
    )


def _pair_order_key(
    pair: _ExactPair,
) -> PairOrderKey:
    """Return ratio, time, span, and stable candidate keys in priority order."""
    outgoing_datetime = _comparison_datetime(pair.outgoing.datetime)
    incoming_datetime = _comparison_datetime(pair.incoming.datetime)
    first_datetime = min(outgoing_datetime, incoming_datetime)
    second_datetime = max(outgoing_datetime, incoming_datetime)
    return (
        pair.ratio,
        pair.time_distance_microseconds,
        first_datetime,
        second_datetime,
        _candidate_order_key(pair.outgoing),
        _candidate_order_key(pair.incoming),
    )


def _build_pair(
    left: ExactTransferCandidate,
    right: ExactTransferCandidate,
    *,
    tolerance: Fraction,
    window_microseconds: int,
) -> _ExactPair | None:
    """Build one valid opposite-sign pair candidate."""
    if left.major_category != right.major_category:
        return None
    if not _same_known_currency(left.amount, right.amount):
        return None
    left_sign = _candidate_sign(left.amount)
    right_sign = _candidate_sign(right.amount)
    if left_sign == right_sign or left_sign == 0 or right_sign == 0:
        return None
    distance = _time_distance_microseconds(left.datetime, right.datetime)
    if distance > window_microseconds:
        return None
    ratio = _relative_mismatch(left.amount, right.amount)
    if ratio is None or ratio > tolerance:
        return None
    outgoing, incoming = (left, right) if left_sign < 0 else (right, left)
    return _ExactPair(
        outgoing=outgoing,
        incoming=incoming,
        ratio=ratio,
        time_distance_microseconds=distance,
    )


def pair_exact_transfer_candidates(
    transactions: Iterable[ExactTransferCandidate],
    *,
    time_window_minutes: int = DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES,
    amount_tolerance: ExactTolerance = DEFAULT_EXACT_TRANSFER_TOLERANCE,
) -> dict[str, tuple[str, str]]:
    """Greedily pair exact transfer candidates without mutating the input.

    Candidates must share a major category and a known currency, have opposite
    non-zero signs, fall inside the integer-microsecond time window, and meet
    the exact relative amount tolerance.  The returned pair tuple is always
    ``(outgoing_transaction_id, incoming_transaction_id)``.  A pair expresses
    only a transfer candidate relation; it is not an account-ownership claim.
    """
    candidate_values = tuple(transactions)
    _validate_input(candidate_values)
    tolerance = _parse_tolerance(amount_tolerance)
    window_microseconds = _parse_time_window(time_window_minutes)

    by_category: dict[str, list[ExactTransferCandidate]] = {}
    for candidate in candidate_values:
        by_category.setdefault(candidate.major_category, []).append(candidate)

    result: dict[str, tuple[str, str]] = {}
    for category in sorted(by_category):
        category_candidates = sorted(by_category[category], key=_candidate_order_key)
        pair_candidates: list[_ExactPair] = []
        for index, left in enumerate(category_candidates):
            for right in category_candidates[index + 1 :]:
                pair = _build_pair(
                    left,
                    right,
                    tolerance=tolerance,
                    window_microseconds=window_microseconds,
                )
                if pair is not None:
                    pair_candidates.append(pair)

        matched_ids: set[str] = set()
        for pair in sorted(pair_candidates, key=_pair_order_key):
            outgoing_id = pair.outgoing.transaction_id
            incoming_id = pair.incoming.transaction_id
            if outgoing_id in matched_ids or incoming_id in matched_ids:
                continue
            group_members = sorted((outgoing_id, incoming_id))
            group_id = f"T_{group_members[0]}_{group_members[1]}"
            result[group_id] = (outgoing_id, incoming_id)
            matched_ids.update(group_members)
    return result


# Descriptive aliases keep the pure matcher discoverable for callers that use
# "match" or "detect" terminology while preserving one implementation.
match_exact_transfer_pairs = pair_exact_transfer_candidates
detect_exact_transfer_pairs = pair_exact_transfer_candidates

__all__ = [
    "DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES",
    "DEFAULT_EXACT_TRANSFER_TOLERANCE",
    "ExactTolerance",
    "ExactTransferCandidate",
    "detect_exact_transfer_pairs",
    "match_exact_transfer_pairs",
    "pair_exact_transfer_candidates",
]
