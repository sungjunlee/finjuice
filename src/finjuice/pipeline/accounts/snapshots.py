"""Canonical before/after snapshots for reversible account corrections."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Mapping

from finjuice.pipeline.accounts.errors import AccountsError
from finjuice.pipeline.accounts.models import (
    ConfirmationState,
    CorrectionSnapshot,
    DateRange,
    HouseholdReporting,
    OwnershipShare,
    SourceAlias,
)


def reversed_snapshot(snapshot: CorrectionSnapshot) -> CorrectionSnapshot:
    """Swap before/after so a correction can be reversed."""
    return CorrectionSnapshot(before=snapshot.after, after=snapshot.before)


def share_record(share: OwnershipShare) -> dict[str, object]:
    """Encode one share without logging financial identity."""
    end = None if share.period.end is None else share.period.end.isoformat()
    return {
        "account_id": share.account_id,
        "party_id": share.party_id,
        "share": str(share.share),
        "start": share.period.start.isoformat(),
        "end": end,
        "confirmation_state": share.confirmation_state,
    }


def parse_share(record: Mapping[str, object]) -> OwnershipShare:
    """Parse one encoded share. Reject floats."""
    raw_share = record["share"]
    if isinstance(raw_share, float):
        raise AccountsError("Ownership share must be an exact decimal.")
    try:
        share = Decimal(str(raw_share))
    except (InvalidOperation, KeyError) as error:
        raise AccountsError("Ownership share is not a decimal.") from error
    if share <= 0 or share > 1:
        raise AccountsError("Ownership share must be in (0, 1].")
    return OwnershipShare(
        account_id=str(record["account_id"]),
        party_id=str(record["party_id"]),
        share=share,
        period=_parse_period(record),
        confirmation_state=_confirmation(record.get("confirmation_state")),
    )


def alias_record(alias: SourceAlias) -> dict[str, object]:
    """Encode one source alias."""
    return {
        "entity_id": alias.entity_id,
        "source_kind": alias.source_kind,
        "source_label": alias.source_label,
        "confirmed": alias.confirmed,
    }


def parse_alias(record: Mapping[str, object]) -> SourceAlias:
    """Parse one encoded source alias."""
    return SourceAlias(
        entity_id=str(record["entity_id"]),
        source_kind=str(record["source_kind"]),
        source_label=str(record["source_label"]),
        confirmed=bool(record.get("confirmed", False)),
    )


def scope_record(scope: HouseholdReporting) -> dict[str, object]:
    """Encode one household reporting row."""
    end = None if scope.period.end is None else scope.period.end.isoformat()
    return {
        "household_id": scope.household_id,
        "account_id": scope.account_id,
        "start": scope.period.start.isoformat(),
        "end": end,
    }


def parse_scope(record: Mapping[str, object]) -> HouseholdReporting:
    """Parse one encoded household reporting row."""
    return HouseholdReporting(
        household_id=str(record["household_id"]),
        account_id=str(record["account_id"]),
        period=_parse_period(record),
    )


def _parse_period(record: Mapping[str, object]) -> DateRange:
    end_raw = record.get("end")
    end = None if end_raw in (None, "") else date.fromisoformat(str(end_raw))
    return DateRange(start=date.fromisoformat(str(record["start"])), end=end)


def _confirmation(value: object) -> ConfirmationState:
    if value == "unconfirmed":
        return "unconfirmed"
    if value == "confirmed":
        return "confirmed"
    raise AccountsError("Share confirmation_state is unknown.")
