"""Unproven cross-artifact overlap used only to quarantine, never to merge."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Final

from finjuice.pipeline.ingest.exact_transactions import ExactMappedRow, canonical_numeric_key
from finjuice.pipeline.storage.sqlite.exact import ExactValue

JSONValue = Any
_MINUTE_TIME_RE: Final = re.compile(r"^\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?$")
_PRECISION_RANK: Final = {
    "day": 0,
    "minute": 1,
    "second": 2,
    "millisecond": 2,
    "microsecond": 2,
}


def canonical_stored_amount_key(coefficient: str, scale: int) -> tuple[str, int]:
    """Compare stored exact amounts without Decimal ambient rounding."""
    sign = "-" if coefficient.startswith("-") else ""
    digits = coefficient.removeprefix("-")
    while scale > 0 and digits.endswith("0"):
        digits = digits[:-1]
        scale -= 1
    digits = digits.lstrip("0") or "0"
    if digits == "0":
        return ("0", 0)
    return (f"{sign}{digits}", scale)


def transaction_effective_at(row: ExactMappedRow) -> str | None:
    """Return source datetime or date text; never invent midnight."""
    temporal = row.temporal
    if temporal.parsed_datetime is not None:
        return temporal.parsed_datetime.isoformat()
    if temporal.parsed_date is not None:
        return temporal.parsed_date.isoformat()
    return None


def transaction_amount_key(row: ExactMappedRow) -> tuple[str, int] | None:
    """Return the interpreted amount key when present, else the source key."""
    amount = row.interpreted_amount or row.source_amount
    if amount is None:
        return None
    return canonical_numeric_key(amount)


def matching_transaction_ids(
    row: ExactMappedRow,
    existing: Sequence[Mapping[str, JSONValue]],
) -> tuple[str, ...]:
    """Return existing IDs that look overlapping but are not source-proven."""
    amount_key = transaction_amount_key(row)
    effective_at = transaction_effective_at(row)
    if amount_key is None or effective_at is None:
        return ()
    matched: list[str] = []
    for candidate in existing:
        if _plausible_overlap(candidate, row, effective_at, amount_key):
            matched.append(str(candidate["transaction_id"]))
    return tuple(matched)


def exact_value_key(value: ExactValue) -> tuple[str, int]:
    """Return the canonical numeric key for an exact value."""
    return canonical_numeric_key(value)


def _plausible_overlap(
    candidate: Mapping[str, JSONValue],
    row: ExactMappedRow,
    effective_at: str,
    amount_key: tuple[str, int],
) -> bool:
    if str(candidate["type_norm"]) != row.type_norm:
        return False
    if not _plausible_money(candidate, row, amount_key):
        return False
    return _plausible_time(candidate, row, effective_at)


def _plausible_money(
    candidate: Mapping[str, JSONValue],
    row: ExactMappedRow,
    amount_key: tuple[str, int],
) -> bool:
    stored = canonical_stored_amount_key(str(candidate["coefficient"]), int(candidate["scale"]))
    if stored != amount_key:
        return False
    if _known_stored_currency(candidate) and _known_row_currency(row):
        return str(candidate["currency_code"]) == row.currency_code
    return True


def _known_stored_currency(candidate: Mapping[str, JSONValue]) -> bool:
    return bool(candidate.get("currency_code")) and not candidate.get("currency_unknown")


def _known_row_currency(row: ExactMappedRow) -> bool:
    return row.currency_code is not None and not row.currency_unknown


def _plausible_time(
    candidate: Mapping[str, JSONValue],
    row: ExactMappedRow,
    incoming_at: str,
) -> bool:
    stored_at = candidate.get("effective_at")
    if stored_at is None:
        return False
    stored_dt = _parse_instant(str(stored_at))
    incoming_dt = _parse_instant(incoming_at)
    if stored_dt is None or incoming_dt is None:
        return str(stored_at) == incoming_at
    if _same_known_instant(stored_dt, incoming_dt):
        return True
    precision = _coarser_precision(candidate, row)
    return _civil_matches(stored_dt, incoming_dt, precision)


def _parse_instant(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


def _same_known_instant(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None or right.tzinfo is None:
        return False
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _coarser_precision(candidate: Mapping[str, JSONValue], row: ExactMappedRow) -> str:
    stored = _stored_precision(candidate)
    incoming = row.temporal.precision or "day"
    stored_rank = _PRECISION_RANK.get(stored, 2)
    incoming_rank = _PRECISION_RANK.get(incoming, 2)
    return stored if stored_rank <= incoming_rank else incoming


def _stored_precision(candidate: Mapping[str, JSONValue]) -> str:
    time_raw = str(candidate.get("time_raw") or "")
    if time_raw == "":
        return "day"
    if _MINUTE_TIME_RE.fullmatch(time_raw) is not None:
        return "minute"
    return "second"


def _civil_matches(left: datetime, right: datetime, precision: str) -> bool:
    left_civil = left.replace(tzinfo=None)
    right_civil = right.replace(tzinfo=None)
    if precision == "day":
        return left_civil.date() == right_civil.date()
    if precision == "minute":
        return left_civil.replace(second=0, microsecond=0) == right_civil.replace(
            second=0, microsecond=0
        )
    return left_civil == right_civil
