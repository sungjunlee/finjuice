"""Typed records for stable family account identity and dated ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Mapping

PartyKind = Literal["unknown", "person", "organization", "household"]
OwnershipState = Literal["unknown", "asserted"]
ConfirmationState = Literal["unconfirmed", "confirmed"]
QueryScope = Literal["personal", "household"]
ChangesetType = Literal["ownership_correction", "alias_bind", "household_scope"]


@dataclass(frozen=True)
class DateRange:
    """Half-open interval ``[start, end)``. ``end is None`` means open-ended."""

    start: date
    end: date | None = None


@dataclass(frozen=True)
class Party:
    """Stable party identity. Household kind is explicit, never inferred."""

    party_id: str
    party_kind: PartyKind = "unknown"
    display_name: str | None = None


@dataclass(frozen=True)
class Account:
    """Stable account identity. Registration always starts as unknown ownership."""

    account_id: str
    account_kind: str
    display_name: str | None = None
    ownership_state: OwnershipState = "unknown"


@dataclass(frozen=True)
class Resource:
    """Stable instrument/resource identity, independent of account nature."""

    resource_id: str
    resource_kind: str
    display_name: str | None = None


@dataclass(frozen=True)
class SourceAlias:
    """One source-specific label bound to a stable entity ID."""

    entity_id: str
    source_kind: str
    source_label: str
    confirmed: bool = False


@dataclass(frozen=True)
class OwnershipShare:
    """Exact dated ownership share. Overlapping party periods are rejected."""

    account_id: str
    party_id: str
    share: Decimal
    period: DateRange
    confirmation_state: ConfirmationState = "unconfirmed"


@dataclass(frozen=True)
class HouseholdReporting:
    """Household report inclusion, distinct from ownership shares."""

    household_id: str
    account_id: str
    period: DateRange


@dataclass(frozen=True)
class AssetClassification:
    """Asset class and liquidity for a resource, not an account kind."""

    resource_id: str
    asset_class: str
    liquidity_policy: str


@dataclass(frozen=True)
class CorrectionSnapshot:
    """Canonical before/after payload for one semantic correction."""

    before: Mapping[str, object]
    after: Mapping[str, object]


@dataclass(frozen=True)
class SemanticChangeset:
    """Reversible meaning correction recorded after a preservation baseline."""

    changeset_id: str
    changeset_type: ChangesetType
    reason: str
    snapshot: CorrectionSnapshot
    reversal_of: str | None = None


@dataclass(frozen=True)
class AccountView:
    """One account as seen in a personal or household query."""

    account: Account
    ownership_state: OwnershipState
    owner_party_ids: tuple[str, ...]
    share_for_party: Decimal | None = None


@dataclass(frozen=True)
class QueryResult:
    """Deterministic query result that always surfaces unknown ownership."""

    as_of: date
    scope: QueryScope
    views: tuple[AccountView, ...]
    unknown_owner_account_ids: tuple[str, ...]
