"""In-memory registry for stable account identity and dated ownership.

This is the M1 domain slice for issue #442. It does not infer owners from
display names, and it does not persist to SQLite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Mapping, TypeVar

from finjuice.pipeline.accounts.errors import AccountsError
from finjuice.pipeline.accounts.ids import new_stable_id
from finjuice.pipeline.accounts.models import (
    Account,
    AccountView,
    AssetClassification,
    HouseholdReporting,
    OwnershipShare,
    OwnershipState,
    Party,
    QueryResult,
    Resource,
    SemanticChangeset,
    SourceAlias,
)
from finjuice.pipeline.accounts.policies import (
    ACCOUNT_KINDS,
    ASSET_CLASSES,
    LIQUIDITY_POLICIES,
)
from finjuice.pipeline.accounts.queries import contains, overlaps, share_total, shares_on_date
from finjuice.pipeline.accounts.snapshots import (
    parse_alias,
    parse_scope,
    parse_share,
    reversed_snapshot,
    share_record,
)

_ONE = Decimal("1")
T = TypeVar("T")


class AccountRegistry:
    """Confirmed identities, aliases, dated shares, and reversible corrections."""

    def __init__(self) -> None:
        self._parties: dict[str, Party] = {}
        self._accounts: dict[str, Account] = {}
        self._resources: dict[str, Resource] = {}
        self._aliases: dict[tuple[str, str], SourceAlias] = {}
        self._shares: list[OwnershipShare] = []
        self._scopes: list[HouseholdReporting] = []
        self._classifications: dict[str, AssetClassification] = {}
        self._changesets: dict[str, SemanticChangeset] = {}
        self._baseline = False

    def mark_baseline(self) -> None:
        """Record that the current identities are the preservation baseline."""
        self._baseline = True

    def register_party(self, party: Party) -> Party:
        """Insert or return an identical party. IDs are never derived from names."""
        return _put_unique(self._parties, party.party_id, party, "Party identity conflict.")

    def register_account(self, account: Account) -> Account:
        """Insert an account. Ownership cannot be asserted at registration."""
        if account.ownership_state != "unknown":
            raise AccountsError("New accounts must start with unknown ownership.")
        if account.account_kind not in ACCOUNT_KINDS:
            raise AccountsError("Account kind is unsupported.")
        return _put_unique(
            self._accounts, account.account_id, account, "Account identity conflict."
        )

    def register_resource(self, resource: Resource) -> Resource:
        """Insert or return an identical resource identity."""
        return _put_unique(
            self._resources, resource.resource_id, resource, "Resource identity conflict."
        )

    def classify_resource(self, classification: AssetClassification) -> AssetClassification:
        """Attach asset class and liquidity without changing account kind."""
        self._require_resource(classification.resource_id)
        if classification.asset_class not in ASSET_CLASSES:
            raise AccountsError("Asset class is unsupported.")
        if classification.liquidity_policy not in LIQUIDITY_POLICIES:
            raise AccountsError("Liquidity policy is unsupported.")
        existing = self._classifications.get(classification.resource_id)
        if existing is None:
            self._classifications[classification.resource_id] = classification
            return classification
        if existing != classification:
            raise AccountsError("Resource classification conflict.")
        return existing

    def bind_alias(self, alias: SourceAlias) -> SourceAlias:
        """Bind a source label to a confirmed entity without creating a new ID."""
        self._require_entity(alias.entity_id)
        key = (alias.source_kind, alias.source_label)
        existing = self._aliases.get(key)
        if existing is None:
            self._aliases[key] = alias
            return alias
        if existing.entity_id != alias.entity_id:
            raise AccountsError("Alias already bound to a different identity.")
        return existing

    def resolve_alias(self, source_kind: str, source_label: str) -> str | None:
        """Resolve a source label. Unknown labels are not guessed."""
        alias = self._aliases.get((source_kind, source_label))
        return None if alias is None else alias.entity_id

    def rename_account(self, account_id: str, display_name: str) -> Account:
        """Change display name only. The stable ID is unchanged."""
        account = self._require_account(account_id)
        updated = Account(
            account_id=account.account_id,
            account_kind=account.account_kind,
            display_name=display_name,
            ownership_state=account.ownership_state,
        )
        self._accounts[account_id] = updated
        return updated

    def aliases_for(self, entity_id: str) -> tuple[SourceAlias, ...]:
        """Return every source alias bound to one entity."""
        return tuple(item for item in self._aliases.values() if item.entity_id == entity_id)

    def get_account(self, account_id: str) -> Account:
        """Return one account identity."""
        return self._require_account(account_id)

    def classification_for(self, resource_id: str) -> AssetClassification | None:
        """Return the explicit resource classification, if any."""
        return self._classifications.get(resource_id)

    def apply_changeset(self, changeset: SemanticChangeset) -> SemanticChangeset:
        """Apply a post-baseline correction. Identical retries are idempotent."""
        if not self._baseline:
            raise AccountsError("Semantic corrections require a recorded baseline.")
        existing = self._changesets.get(changeset.changeset_id)
        if existing is not None:
            if _changeset_equal(existing, changeset):
                return existing
            raise AccountsError("Changeset idempotency conflict.")
        self._dispatch_changeset(changeset)
        self._changesets[changeset.changeset_id] = changeset
        return changeset

    def reverse_changeset(self, changeset_id: str, reason: str) -> SemanticChangeset:
        """Record a reversal with swapped before/after and a new reason."""
        original = self._changesets.get(changeset_id)
        if original is None:
            raise AccountsError("Unknown changeset.")
        if original.reversal_of is not None:
            raise AccountsError("A reversal cannot be reversed in place.")
        existing = _find_reversal(self._changesets, changeset_id)
        if existing is not None:
            return existing
        reversal = SemanticChangeset(
            changeset_id=new_stable_id(),
            changeset_type=original.changeset_type,
            reason=reason,
            snapshot=reversed_snapshot(original.snapshot),
            reversal_of=changeset_id,
        )
        return self.apply_changeset(reversal)

    def changeset(self, changeset_id: str) -> SemanticChangeset:
        """Return one recorded correction."""
        item = self._changesets.get(changeset_id)
        if item is None:
            raise AccountsError("Unknown changeset.")
        return item

    def query_personal(self, party_id: str, as_of: date) -> QueryResult:
        """Return accounts this party confirmed-owns on ``as_of``."""
        self._require_party(party_id)
        views: list[AccountView] = []
        for account in self._sorted_accounts():
            shares = shares_on_date(self._shares, account.account_id, as_of)
            mine = tuple(item for item in shares if item.party_id == party_id)
            if not mine:
                continue
            views.append(_view_from_shares(account, shares, mine[0].share))
        return QueryResult(
            as_of=as_of,
            scope="personal",
            views=tuple(views),
            unknown_owner_account_ids=self._unknown_owner_ids(),
        )

    def query_household(self, household_id: str, as_of: date) -> QueryResult:
        """Return household reporting-scope accounts, not ownership shares."""
        household = self._require_party(household_id)
        if household.party_kind != "household":
            raise AccountsError("Household query requires a household party.")
        views: list[AccountView] = []
        for scope in self._scopes:
            if scope.household_id != household_id or not contains(scope.period, as_of):
                continue
            account = self._require_account(scope.account_id)
            shares = shares_on_date(self._shares, account.account_id, as_of)
            views.append(_view_from_shares(account, shares, None))
        views.sort(key=lambda item: item.account.account_id)
        return QueryResult(
            as_of=as_of,
            scope="household",
            views=tuple(views),
            unknown_owner_account_ids=self._unknown_owner_ids(),
        )

    def _dispatch_changeset(self, changeset: SemanticChangeset) -> None:
        if changeset.changeset_type == "ownership_correction":
            self._apply_ownership(changeset)
            return
        if changeset.changeset_type == "alias_bind":
            self._apply_alias(changeset)
            return
        if changeset.changeset_type == "household_scope":
            self._apply_scope(changeset)
            return
        raise AccountsError("Changeset type is unsupported.")

    def _apply_ownership(self, changeset: SemanticChangeset) -> None:
        account_id = _required_text(changeset.snapshot.after, "account_id")
        current = self._ownership_payload(account_id)
        if _canonical_payload(changeset.snapshot.before) != current:
            raise AccountsError("Changeset before-state does not match.")
        shares = _parse_shares(changeset.snapshot.after.get("shares"))
        _validate_share_set(shares, account_id)
        state = _as_ownership_state(_required_text(changeset.snapshot.after, "ownership_state"))
        if state == "asserted" and not shares:
            raise AccountsError("Asserted ownership requires dated shares.")
        if state == "unknown" and shares:
            raise AccountsError("Unknown ownership cannot carry shares.")
        self._shares = [item for item in self._shares if item.account_id != account_id]
        self._shares.extend(shares)
        account = self._require_account(account_id)
        self._accounts[account_id] = Account(
            account_id=account.account_id,
            account_kind=account.account_kind,
            display_name=account.display_name,
            ownership_state=state,
        )

    def _apply_alias(self, changeset: SemanticChangeset) -> None:
        after = changeset.snapshot.after
        source_kind = _required_text(after, "source_kind")
        source_label = _required_text(after, "source_label")
        before_entity = changeset.snapshot.before.get("entity_id")
        current = self.resolve_alias(source_kind, source_label)
        if current != before_entity:
            raise AccountsError("Changeset before-state does not match.")
        key = (source_kind, source_label)
        entity_id = after.get("entity_id")
        if entity_id in (None, ""):
            self._aliases.pop(key, None)
            return
        self._require_entity(str(entity_id))
        self._aliases[key] = parse_alias(after)

    def _apply_scope(self, changeset: SemanticChangeset) -> None:
        after = parse_scope(changeset.snapshot.after)
        self._require_account(after.account_id)
        household = self._require_party(after.household_id)
        if household.party_kind != "household":
            raise AccountsError("Reporting scope requires a household party.")
        self._scopes = [
            item
            for item in self._scopes
            if not (item.household_id == after.household_id and item.account_id == after.account_id)
        ]
        if changeset.snapshot.after.get("included", True):
            self._scopes.append(after)

    def _ownership_payload(self, account_id: str) -> dict[str, object]:
        account = self._require_account(account_id)
        shares = tuple(
            share_record(item) for item in self._shares if item.account_id == account_id
        )
        return {
            "account_id": account_id,
            "ownership_state": account.ownership_state,
            "shares": list(shares),
        }

    def _unknown_owner_ids(self) -> tuple[str, ...]:
        return tuple(
            account.account_id
            for account in self._sorted_accounts()
            if account.ownership_state == "unknown"
        )

    def _sorted_accounts(self) -> tuple[Account, ...]:
        return tuple(self._accounts[key] for key in sorted(self._accounts))

    def _require_party(self, party_id: str) -> Party:
        party = self._parties.get(party_id)
        if party is None:
            raise AccountsError("Unknown party.")
        return party

    def _require_account(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountsError("Unknown account.")
        return account

    def _require_resource(self, resource_id: str) -> Resource:
        resource = self._resources.get(resource_id)
        if resource is None:
            raise AccountsError("Unknown resource.")
        return resource

    def _require_entity(self, entity_id: str) -> None:
        if entity_id in self._parties or entity_id in self._accounts:
            return
        if entity_id in self._resources:
            return
        raise AccountsError("Unknown entity.")


def _put_unique(store: dict[str, T], key: str, value: T, conflict: str) -> T:
    existing = store.get(key)
    if existing is None:
        store[key] = value
        return value
    if existing != value:
        raise AccountsError(conflict)
    return existing


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise AccountsError("Changeset payload is incomplete.")
    return value


def _parse_shares(raw: object) -> list[OwnershipShare]:
    if raw in (None, ()):
        return []
    if not isinstance(raw, list):
        raise AccountsError("Ownership shares must be a list.")
    return [parse_share(item) for item in raw]


def _validate_share_set(shares: list[OwnershipShare], account_id: str) -> None:
    seen_parties: list[OwnershipShare] = []
    for share in shares:
        if share.account_id != account_id:
            raise AccountsError("Share account_id does not match changeset.")
        if share.confirmation_state != "confirmed":
            raise AccountsError("Asserted shares must be confirmed.")
        for other in seen_parties:
            if share.party_id == other.party_id and overlaps(share.period, other.period):
                raise AccountsError("Ownership periods overlap for one party.")
        seen_parties.append(share)
    starts = {item.period.start for item in shares}
    for as_of in sorted(starts):
        active = [item for item in shares if contains(item.period, as_of)]
        if share_total(active) != _ONE:
            raise AccountsError("Confirmed shares on a date must sum to 1.")


def _as_ownership_state(value: str) -> OwnershipState:
    if value == "unknown":
        return "unknown"
    if value == "asserted":
        return "asserted"
    raise AccountsError("Ownership state is unsupported.")


def _canonical_payload(payload: Mapping[str, object]) -> dict[str, object]:
    data = dict(payload)
    shares = data.get("shares")
    if isinstance(shares, (list, tuple)):
        data["shares"] = [dict(item) for item in shares]
    return data


def _view_from_shares(
    account: Account,
    shares: tuple[OwnershipShare, ...],
    share_for_party: Decimal | None,
) -> AccountView:
    owners = tuple(sorted({item.party_id for item in shares}))
    return AccountView(
        account=account,
        ownership_state=account.ownership_state,
        owner_party_ids=owners,
        share_for_party=share_for_party,
    )


def _changeset_equal(left: SemanticChangeset, right: SemanticChangeset) -> bool:
    return (
        left.changeset_id == right.changeset_id
        and left.changeset_type == right.changeset_type
        and left.reason == right.reason
        and dict(left.snapshot.before) == dict(right.snapshot.before)
        and dict(left.snapshot.after) == dict(right.snapshot.after)
        and left.reversal_of == right.reversal_of
    )


def _find_reversal(
    changesets: Mapping[str, SemanticChangeset],
    changeset_id: str,
) -> SemanticChangeset | None:
    for item in changesets.values():
        if item.reversal_of == changeset_id:
            return item
    return None
