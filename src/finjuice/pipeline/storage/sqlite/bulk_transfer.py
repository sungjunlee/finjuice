"""Exact bulk transfer recompute over the whole transaction snapshot.

Frozen ``pair_exact_transfer_candidates`` assumes the caller already filtered
transfer-like rows; it does not decide transfer semantics. This adapter uses
canonical ``type_norm == "transfer"`` plus the legacy ``type_raw`` contains
``이체`` compatibility predicate.

``is_transfer_candidate`` means transfer-like, including unmatched and unusable
clock/currency rows. ``is_transfer`` and ``transfer_group_id`` are only set for
confirmed exact-matched members. Pairing uses observation ``effective_at``
(event/as-of). ``observed_at``/``collected_at`` are never used to invent a clock.
Known naive clocks are a separate civil-clock group and are never mixed with
aware clocks. Unknown-zone rows stay unconfirmed candidates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from re import compile as regexp
from typing import Any, Literal, cast

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.mutations import MutationContext
from finjuice.pipeline.transfer.exact_pairing import (
    DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES,
    DEFAULT_EXACT_TRANSFER_TOLERANCE,
    ExactTransferCandidate,
    pair_exact_transfer_candidates,
)

JSONValue = Any
_ISO_DATETIME = regexp(
    r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?\Z"
)
_MAX_TOLERANCE_LEXEME = 32
_MAX_TOLERANCE_EXPONENT = 18


@dataclass(frozen=True)
class BulkTransferCommand:
    """Replayable whole-dataset transfer intent with explicit matcher options."""

    time_window_minutes: int = DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES
    amount_tolerance: str = str(DEFAULT_EXACT_TRANSFER_TOLERANCE)

    def __post_init__(self) -> None:
        _validate_time_window(self.time_window_minutes)
        _validate_amount_tolerance(self.amount_tolerance)

    def payload(self) -> dict[str, JSONValue]:
        """Return the stable command payload used for idempotent replay."""
        return {
            "amount_tolerance": self.amount_tolerance,
            "operation": "recompute",
            "time_window_minutes": self.time_window_minutes,
        }


@dataclass(frozen=True)
class BulkTransferChange:
    """One planned derived-transfer write for a snapshot transaction."""

    transaction_id: str
    before: Mapping[str, JSONValue]
    after: Mapping[str, JSONValue]


@dataclass(frozen=True)
class BulkTransferPlan:
    """Shared transfer computation used by dry-run preview and the writer."""

    total: int
    updated: int
    unsupported: int
    candidate_rows: int
    candidates_considered: int
    pairs_found: int
    paired_rows: int
    confirmed_transfer_rows: int
    unconfirmed_candidate_rows: int
    unsupported_missing_timezone: int
    unsupported_malformed_time: int
    changes: tuple[BulkTransferChange, ...]

    def result(self) -> dict[str, JSONValue]:
        """Return float-free integer counts shared by preview and write."""
        return {
            "candidate_rows": self.candidate_rows,
            "candidates_considered": self.candidates_considered,
            "changed": self.updated > 0,
            "confirmed_transfer_rows": self.confirmed_transfer_rows,
            "paired_rows": self.paired_rows,
            "pairs_found": self.pairs_found,
            "pairs_linked": self.paired_rows,
            "total": self.total,
            "unchanged": self.total - self.updated,
            "unconfirmed_candidate_rows": self.unconfirmed_candidate_rows,
            "unsupported": self.unsupported,
            "unsupported_malformed_time": self.unsupported_malformed_time,
            "unsupported_missing_timezone": self.unsupported_missing_timezone,
            "updated": self.updated,
        }


def plan_bulk_transfer(
    context: MutationContext,
    command: BulkTransferCommand,
) -> BulkTransferPlan:
    """Compute derived transfer fields under the pinned snapshot without writing."""
    rows = context.load_bulk_transactions()
    classified = tuple(_classify_row(row) for row in rows)
    pairs = _pair_eligible(classified, command)
    membership = _pair_membership(pairs)
    changes = _transfer_changes(classified, membership)
    return _plan_from_classified(classified, pairs, membership, changes)


def apply_bulk_transfer(
    context: MutationContext,
    command: BulkTransferCommand,
) -> dict[str, JSONValue]:
    """Write planned transfer changes inside the caller's mutation transaction."""
    plan = plan_bulk_transfer(context, command)
    for change in plan.changes:
        context.update_transaction_derived_state(
            change.transaction_id,
            change.after,
            before=change.before,
        )
    return plan.result()


def preview_bulk_transfer(
    context: MutationContext,
    command: BulkTransferCommand,
) -> dict[str, JSONValue]:
    """Return the write counts without updating derived transfer fields."""
    return plan_bulk_transfer(context, command).result()


def transfer_derived_state(row: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Return the comparable derived transfer snapshot for one loaded row."""
    return {
        "is_transfer": row["is_transfer"],
        "is_transfer_candidate": row["is_transfer_candidate"],
        "transfer_group_id": row["transfer_group_id"],
    }


def project_supported_timestamp(row: Mapping[str, JSONValue]) -> datetime | None:
    """Project event/as-of ``effective_at`` when the timezone fact is known.

    Date-only values, Excel serials, and timezone inference are rejected.
    Observation collection timestamps are not a substitute event clock.
    """
    if row.get("timezone_state") != "known":
        return None
    raw = row.get("effective_at")
    return parse_supported_iso_datetime(raw if isinstance(raw, str) else None)


def parse_supported_iso_datetime(raw: str | None) -> datetime | None:
    """Parse a strict ISO-8601 datetime, leaving naive and aware values distinct."""
    if raw is None:
        return None
    match = _ISO_DATETIME.fullmatch(raw)
    if match is None:
        return None
    parts = match.groups()
    try:
        value = _naive_datetime(parts)
    except ValueError:
        return None
    return _apply_explicit_offset(value, parts[7])


def is_transfer_like(row: Mapping[str, JSONValue]) -> bool:
    """Return whether a source row is transfer-like for candidate marking.

    Canonical rows use ``type_norm == "transfer"``. Legacy Banksalad rows that
    still carry ``이체`` in ``type_raw`` remain eligible for compatibility.
    """
    type_norm = row.get("type_norm")
    if isinstance(type_norm, str) and type_norm.strip().lower() == "transfer":
        return True
    type_raw = row.get("type_raw")
    return isinstance(type_raw, str) and "이체" in type_raw


def _naive_datetime(parts: tuple[str | None, ...]) -> datetime:
    year, month, day, hour, minute, second, fraction, _offset = parts
    return datetime(
        int(str(year)),
        int(str(month)),
        int(str(day)),
        int(str(hour)),
        int(str(minute)),
        int(str(second)),
        _microseconds(fraction),
    )


@dataclass(frozen=True)
class _ClassifiedRow:
    transaction_id: str
    row: Mapping[str, JSONValue]
    transfer_like: bool
    candidate: ExactTransferCandidate | None
    reason: str | None


def _classify_row(row: Mapping[str, JSONValue]) -> _ClassifiedRow:
    """Mark transfer-like rows; only usable ones become exact matcher input."""
    transaction_id = str(row["transaction_id"])
    if not is_transfer_like(row):
        return _ClassifiedRow(transaction_id, row, False, None, None)
    candidate, reason = _exact_candidate(row, transaction_id)
    return _ClassifiedRow(transaction_id, row, True, candidate, reason)


def _exact_candidate(
    row: Mapping[str, JSONValue],
    transaction_id: str,
) -> tuple[ExactTransferCandidate | None, str | None]:
    reason = _unsupported_reason(row)
    if reason is not None:
        return None, reason
    amount = _row_amount(row)
    instant = project_supported_timestamp(row)
    if amount is None or instant is None:
        return None, "malformed_time"
    return (
        ExactTransferCandidate(
            transaction_id=transaction_id,
            datetime=instant,
            amount=amount,
            account=str(row.get("account_text") or ""),
            counterparty=str(row.get("counterparty") or ""),
            major_category=str(row.get("major_raw") or ""),
        ),
        None,
    )


def _unsupported_reason(row: Mapping[str, JSONValue]) -> str | None:
    """Classify why a transfer-like row cannot enter the exact matcher."""
    if row.get("timezone_state") != "known":
        return "missing_timezone"
    if project_supported_timestamp(row) is None:
        return "malformed_time"
    amount = _row_amount(row)
    if amount is None or amount.currency_unknown or amount.currency is None:
        return "unknown_currency"
    return None


def _pair_eligible(
    classified: Sequence[_ClassifiedRow],
    command: BulkTransferCommand,
) -> dict[str, tuple[str, str]]:
    """Pair naive and aware groups separately; mixed clocks are not comparable."""
    naive = [
        item.candidate
        for item in classified
        if item.candidate is not None and _is_naive_candidate(item.candidate)
    ]
    aware = [
        item.candidate
        for item in classified
        if item.candidate is not None and _is_aware_candidate(item.candidate)
    ]
    pairs: dict[str, tuple[str, str]] = {}
    pairs.update(_apply_exact_matcher(naive, command))
    pairs.update(_apply_exact_matcher(aware, command))
    return pairs


def _apply_exact_matcher(
    candidates: Sequence[ExactTransferCandidate],
    command: BulkTransferCommand,
) -> dict[str, tuple[str, str]]:
    """Run the frozen exact matcher, including empty groups, to validate options."""
    try:
        return pair_exact_transfer_candidates(
            candidates,
            time_window_minutes=command.time_window_minutes,
            amount_tolerance=command.amount_tolerance,
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError(str(exc)) from exc


def _pair_membership(pairs: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """Map each paired transaction to its deterministic stable-ID group key."""
    membership: dict[str, str] = {}
    for group_id, members in pairs.items():
        for transaction_id in members:
            membership[transaction_id] = group_id
    return membership


def _transfer_changes(
    classified: Sequence[_ClassifiedRow],
    membership: Mapping[str, str],
) -> tuple[BulkTransferChange, ...]:
    return tuple(
        change
        for change in (_planned_transfer_change(item, membership) for item in classified)
        if change is not None
    )


def _planned_transfer_change(
    item: _ClassifiedRow,
    membership: Mapping[str, str],
) -> BulkTransferChange | None:
    after = _derived_after(item, membership)
    before = transfer_derived_state(item.row)
    if before == after:
        return None
    return BulkTransferChange(item.transaction_id, before, after)


def _derived_after(
    item: _ClassifiedRow,
    membership: Mapping[str, str],
) -> dict[str, JSONValue]:
    """Whole recompute clears obsolete pair state, including ineligible rows."""
    if not item.transfer_like:
        return {
            "is_transfer": False,
            "is_transfer_candidate": False,
            "transfer_group_id": None,
        }
    group_id = membership.get(item.transaction_id)
    return {
        "is_transfer": group_id is not None,
        "is_transfer_candidate": True,
        "transfer_group_id": group_id,
    }


def _plan_from_classified(
    classified: Sequence[_ClassifiedRow],
    pairs: Mapping[str, tuple[str, str]],
    membership: Mapping[str, str],
    changes: tuple[BulkTransferChange, ...],
) -> BulkTransferPlan:
    candidate_rows = sum(item.transfer_like for item in classified)
    considered = sum(item.candidate is not None for item in classified)
    paired_rows = len(membership)
    unsupported = sum(item.transfer_like and item.candidate is None for item in classified)
    return BulkTransferPlan(
        total=len(classified),
        updated=len(changes),
        unsupported=unsupported,
        candidate_rows=candidate_rows,
        candidates_considered=considered,
        pairs_found=len(pairs),
        paired_rows=paired_rows,
        confirmed_transfer_rows=paired_rows,
        unconfirmed_candidate_rows=candidate_rows - paired_rows,
        unsupported_missing_timezone=_reason_count(classified, "missing_timezone"),
        unsupported_malformed_time=_reason_count(classified, "malformed_time"),
        changes=changes,
    )


def _reason_count(classified: Sequence[_ClassifiedRow], reason: str) -> int:
    return sum(item.reason == reason for item in classified)


def _row_amount(row: Mapping[str, JSONValue]) -> ExactValue | None:
    """Reconstruct stored exact money, or None when the amount is not usable."""
    if not _usable_money_fields(row):
        return None
    try:
        return _exact_money(row)
    except ValueError:
        return None


def _usable_money_fields(row: Mapping[str, JSONValue]) -> bool:
    coefficient = row.get("amount_coefficient")
    scale = row.get("amount_scale")
    kind = row.get("amount_value_kind")
    origin = row.get("amount_origin_kind")
    return (
        isinstance(coefficient, str)
        and isinstance(scale, int)
        and kind == "money"
        and origin in {"source", "migration", "calculated"}
    )


def _exact_money(row: Mapping[str, JSONValue]) -> ExactValue:
    unknown = bool(row.get("currency_unknown"))
    lexical = row.get("amount_lexical")
    currency = row.get("currency")
    origin = cast(Literal["source", "migration", "calculated"], row.get("amount_origin_kind"))
    return ExactValue(
        coefficient=str(row["amount_coefficient"]),
        scale=int(str(row["amount_scale"])),
        lexical=None if lexical is None else str(lexical),
        value_kind="money",
        origin_kind=origin,
        currency=None if unknown or currency is None else str(currency),
        currency_unknown=unknown,
    )


def _is_naive_candidate(candidate: ExactTransferCandidate | None) -> bool:
    return candidate is not None and candidate.datetime.tzinfo is None


def _is_aware_candidate(candidate: ExactTransferCandidate | None) -> bool:
    return (
        candidate is not None
        and candidate.datetime.tzinfo is not None
        and candidate.datetime.utcoffset() is not None
    )


def _microseconds(fraction: str | None) -> int:
    if fraction is None:
        return 0
    return int(fraction.ljust(6, "0"))


def _apply_explicit_offset(value: datetime, offset: str | None) -> datetime | None:
    """Attach only an explicit offset; never infer local timezone."""
    if offset is None:
        return value
    if offset == "Z":
        return value.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    hours = int(offset[1:3])
    minutes = int(offset[4:6])
    if hours > 23 or minutes > 59:
        return None
    return value.replace(tzinfo=timezone(timedelta(hours=sign * hours, minutes=sign * minutes)))


def _validate_time_window(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MutationValidationError("time_window_minutes must be a non-negative integer.")


def _validate_amount_tolerance(value: object) -> None:
    """Reject invalid tolerance before pairing, including empty candidate groups."""
    _guard_tolerance_lexeme(value)
    try:
        pair_exact_transfer_candidates(
            (),
            time_window_minutes=DEFAULT_EXACT_TRANSFER_TIME_WINDOW_MINUTES,
            amount_tolerance=str(value),
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError(str(exc)) from exc


def _guard_tolerance_lexeme(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, str) or not value:
        raise MutationValidationError("amount_tolerance must be exact decimal text.")
    if len(value) > _MAX_TOLERANCE_LEXEME or any(ch.isspace() for ch in value):
        raise MutationValidationError("amount_tolerance must be exact decimal text.")
    lowered = value.lower()
    if "nan" in lowered or "inf" in lowered:
        raise MutationValidationError("amount_tolerance must be a finite decimal.")
    _reject_huge_tolerance_exponent(value)


def _reject_huge_tolerance_exponent(value: str) -> None:
    marker = value.lower().find("e")
    if marker < 0:
        return
    digits = value[marker + 1 :].lstrip("+-")
    if not digits.isdigit() or int(digits) > _MAX_TOLERANCE_EXPONENT:
        raise MutationValidationError("amount_tolerance must be exact decimal text.")


__all__ = [
    "BulkTransferCommand",
    "BulkTransferPlan",
    "apply_bulk_transfer",
    "is_transfer_like",
    "plan_bulk_transfer",
    "preview_bulk_transfer",
]
