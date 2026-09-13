"""Structure and M1 acceptance tests for family account stable IDs.

Public types and helpers are defined in ``finjuice.pipeline.accounts``
submodules and re-exported from the package. Behavioral tests cover issue
#442: identity after rename/reimport, unknown ownership, period/joint
versus household queries, and reversible post-baseline corrections.
"""

from __future__ import annotations

import ast
import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finjuice.pipeline.accounts.ids import new_stable_id
from finjuice.pipeline.accounts.models import (
    Account,
    AssetClassification,
    CorrectionSnapshot,
    DateRange,
    HouseholdReporting,
    OwnershipShare,
    Party,
    Resource,
    SemanticChangeset,
    SourceAlias,
)
from finjuice.pipeline.accounts.registry import AccountRegistry

ACCOUNTS_DIR = Path("src/finjuice/pipeline/accounts")
PACKAGE = "finjuice.pipeline.accounts"
MODELS_MODULE = "finjuice.pipeline.accounts.models"
REGISTRY_MODULE = "finjuice.pipeline.accounts.registry"
IDS_MODULE = "finjuice.pipeline.accounts.ids"
POLICIES_MODULE = "finjuice.pipeline.accounts.policies"
ERRORS_MODULE = "finjuice.pipeline.accounts.errors"
QUERIES_MODULE = "finjuice.pipeline.accounts.queries"
SNAPSHOTS_MODULE = "finjuice.pipeline.accounts.snapshots"

MODEL_NAMES = (
    "Account",
    "AccountView",
    "AssetClassification",
    "CorrectionSnapshot",
    "DateRange",
    "HouseholdReporting",
    "OwnershipShare",
    "Party",
    "QueryResult",
    "Resource",
    "SemanticChangeset",
    "SourceAlias",
)
POLICY_CONSTANTS = ("ACCOUNT_KINDS", "ASSET_CLASSES", "LIQUIDITY_POLICIES")

PARTY_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
PARTY_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"
HOUSEHOLD = "cccccccc-cccc-4ccc-8ccc-ccccccccccc3"
ACC_IRP = "dddddddd-dddd-4ddd-8ddd-ddddddddddd4"
ACC_UNKNOWN = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5"
RES_FUND = "ffffffff-ffff-4fff-8fff-fffffffffff6"
CHANGESET_OWN = "12121212-1212-4121-8121-121212121217"


def _core_account_paths() -> list[Path]:
    return sorted(ACCOUNTS_DIR.glob("*.py"))


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_package_reexports_definition_identity() -> None:
    """Public names stay identity-equal to their definition modules."""
    package = importlib.import_module(PACKAGE)
    models = importlib.import_module(MODELS_MODULE)
    registry = importlib.import_module(REGISTRY_MODULE)
    ids = importlib.import_module(IDS_MODULE)
    policies = importlib.import_module(POLICIES_MODULE)
    errors = importlib.import_module(ERRORS_MODULE)

    for name in MODEL_NAMES:
        assert getattr(package, name) is getattr(models, name)
        assert getattr(models, name).__module__ == MODELS_MODULE
    assert package.AccountRegistry is registry.AccountRegistry
    assert registry.AccountRegistry.__module__ == REGISTRY_MODULE
    assert package.new_stable_id is ids.new_stable_id
    assert ids.new_stable_id.__module__ == IDS_MODULE
    assert package.AccountsError is errors.AccountsError
    assert errors.AccountsError.__module__ == ERRORS_MODULE
    assert package.liquidity_for_account_kind is policies.liquidity_for_account_kind
    assert policies.liquidity_for_account_kind.__module__ == POLICIES_MODULE
    for name in POLICY_CONSTANTS:
        assert getattr(package, name) is getattr(policies, name)


def test_accounts_package_is_the_unique_home() -> None:
    """Moved names are defined once, not copied into the package barrel."""
    init_text = (ACCOUNTS_DIR / "__init__.py").read_text(encoding="utf-8")
    models_text = (ACCOUNTS_DIR / "models.py").read_text(encoding="utf-8")
    registry_text = (ACCOUNTS_DIR / "registry.py").read_text(encoding="utf-8")

    assert "class AccountRegistry" in registry_text
    assert "class AccountRegistry" not in init_text
    assert "class Party" in models_text
    assert "class Party" not in init_text
    assert "def new_stable_id" not in init_text
    assert "def liquidity_for_account_kind" not in (ACCOUNTS_DIR / "registry.py").read_text(
        encoding="utf-8"
    )


def test_accounts_modules_do_not_import_cli_or_cycle_parents() -> None:
    """The new package stays free of CLI and parent/sibling import cycles."""
    for path in _core_account_paths():
        imported = _imported_modules(path)
        assert not any(
            item == "finjuice.pipeline.cli" or item.startswith("finjuice.pipeline.cli.")
            for item in imported
        )
        assert "finjuice.pipeline.storage.sqlite" not in imported
        if path.name == "models.py":
            assert not any(item.startswith("finjuice.pipeline.accounts.") for item in imported)
        if path.name in {"ids.py", "errors.py", "policies.py"}:
            assert not any(item.startswith("finjuice.pipeline.accounts.") for item in imported)


def test_new_stable_id_is_opaque_uuid_not_derived_from_label() -> None:
    """Stable IDs are UUIDv4 strings and do not encode display names."""
    first = new_stable_id()
    second = new_stable_id()

    assert first != second
    assert first == first.lower()
    assert "bank" not in first
    assert len(first) == 36


def _seed_identities(registry: AccountRegistry) -> AccountRegistry:
    registry.register_party(Party(party_id=PARTY_A, party_kind="person", display_name="Member-A"))
    registry.register_party(Party(party_id=PARTY_B, party_kind="person", display_name="Member-B"))
    registry.register_party(
        Party(party_id=HOUSEHOLD, party_kind="household", display_name="Household")
    )
    registry.register_account(
        Account(account_id=ACC_IRP, account_kind="irp.v1", display_name="Broker IRP")
    )
    registry.register_account(
        Account(
            account_id=ACC_UNKNOWN,
            account_kind="deposit.v1",
            display_name="Member-A Mystery Deposit",
        )
    )
    registry.register_resource(Resource(resource_id=RES_FUND, resource_kind="fund.v1"))
    registry.bind_alias(
        SourceAlias(
            entity_id=ACC_IRP,
            source_kind="banksalad",
            source_label="Broker IRP",
            confirmed=True,
        )
    )
    return registry


def test_rename_new_source_and_reimport_keep_confirmed_identity_and_ownership() -> None:
    """Confirmed account ID and ownership survive rename, new source, reimport."""
    registry = _seed_identities(AccountRegistry())
    registry.mark_baseline()
    before = {
        "account_id": ACC_IRP,
        "ownership_state": "unknown",
        "shares": [],
    }
    after = {
        "account_id": ACC_IRP,
        "ownership_state": "asserted",
        "shares": [
            {
                "account_id": ACC_IRP,
                "party_id": PARTY_A,
                "share": "1",
                "start": "2024-01-01",
                "end": None,
                "confirmation_state": "confirmed",
            }
        ],
    }
    registry.apply_changeset(
        SemanticChangeset(
            changeset_id=CHANGESET_OWN,
            changeset_type="ownership_correction",
            reason="Confirmed IRP owner from screenshot review.",
            snapshot=CorrectionSnapshot(before=before, after=after),
        )
    )

    renamed = registry.rename_account(ACC_IRP, "Broker IRP Relabeled")
    registry.bind_alias(
        SourceAlias(
            entity_id=ACC_IRP,
            source_kind="screenshot",
            source_label="IRP capture 2024",
            confirmed=True,
        )
    )
    reimported = registry.bind_alias(
        SourceAlias(
            entity_id=ACC_IRP,
            source_kind="banksalad",
            source_label="Broker IRP",
            confirmed=True,
        )
    )

    assert renamed.account_id == ACC_IRP
    assert renamed.display_name == "Broker IRP Relabeled"
    assert renamed.account_kind == "irp.v1"
    assert registry.resolve_alias("banksalad", "Broker IRP") == ACC_IRP
    assert registry.resolve_alias("screenshot", "IRP capture 2024") == ACC_IRP
    assert registry.resolve_alias("banksalad", "Broker IRP Relabeled") is None
    assert reimported.entity_id == ACC_IRP
    personal = registry.query_personal(PARTY_A, date(2024, 6, 1))
    assert personal.views[0].account.account_id == ACC_IRP
    assert personal.views[0].share_for_party == Decimal("1")
    assert personal.views[0].ownership_state == "asserted"


def test_unknown_owner_is_not_inferred_from_display_name() -> None:
    """Unknown ownership stays unknown and is listed on queries."""
    registry = _seed_identities(AccountRegistry())

    account = registry.get_account(ACC_UNKNOWN)
    personal = registry.query_personal(PARTY_A, date(2024, 6, 1))

    assert account.ownership_state == "unknown"
    assert account.display_name == "Member-A Mystery Deposit"
    assert personal.views == ()
    assert ACC_UNKNOWN in personal.unknown_owner_account_ids
    assert ACC_IRP in personal.unknown_owner_account_ids
    with pytest.raises(Exception, match="unknown ownership"):
        registry.register_account(
            Account(
                account_id=new_stable_id(),
                account_kind="deposit.v1",
                ownership_state="asserted",
            )
        )


def test_period_joint_ownership_and_household_scope_are_distinct() -> None:
    """Joint dated shares and household reporting scope do not collapse."""
    registry = _seed_identities(AccountRegistry())
    registry.mark_baseline()
    shares = [
        {
            "account_id": ACC_IRP,
            "party_id": PARTY_A,
            "share": "0.6",
            "start": "2024-01-01",
            "end": "2025-07-01",
            "confirmation_state": "confirmed",
        },
        {
            "account_id": ACC_IRP,
            "party_id": PARTY_B,
            "share": "0.4",
            "start": "2024-01-01",
            "end": "2025-07-01",
            "confirmation_state": "confirmed",
        },
        {
            "account_id": ACC_IRP,
            "party_id": PARTY_A,
            "share": "1",
            "start": "2025-07-01",
            "end": None,
            "confirmation_state": "confirmed",
        },
    ]
    registry.apply_changeset(
        SemanticChangeset(
            changeset_id=CHANGESET_OWN,
            changeset_type="ownership_correction",
            reason="Joint IRP split, then sole owner after July.",
            snapshot=CorrectionSnapshot(
                before={
                    "account_id": ACC_IRP,
                    "ownership_state": "unknown",
                    "shares": [],
                },
                after={
                    "account_id": ACC_IRP,
                    "ownership_state": "asserted",
                    "shares": shares,
                },
            ),
        )
    )
    registry.apply_changeset(
        SemanticChangeset(
            changeset_id=new_stable_id(),
            changeset_type="household_scope",
            reason="Include IRP and unknown deposit in household reports.",
            snapshot=CorrectionSnapshot(
                before={"included": False},
                after={
                    "household_id": HOUSEHOLD,
                    "account_id": ACC_IRP,
                    "start": "2024-01-01",
                    "end": None,
                    "included": True,
                },
            ),
        )
    )
    registry.apply_changeset(
        SemanticChangeset(
            changeset_id=new_stable_id(),
            changeset_type="household_scope",
            reason="Unknown deposit stays in household scope without an owner.",
            snapshot=CorrectionSnapshot(
                before={"included": False},
                after={
                    "household_id": HOUSEHOLD,
                    "account_id": ACC_UNKNOWN,
                    "start": "2024-01-01",
                    "end": None,
                    "included": True,
                },
            ),
        )
    )

    personal_a = registry.query_personal(PARTY_A, date(2025, 1, 15))
    personal_b = registry.query_personal(PARTY_B, date(2025, 1, 15))
    personal_a_later = registry.query_personal(PARTY_A, date(2025, 7, 1))
    personal_b_later = registry.query_personal(PARTY_B, date(2025, 7, 1))
    household = registry.query_household(HOUSEHOLD, date(2025, 1, 15))

    assert personal_a.scope == "personal"
    assert personal_a.views[0].share_for_party == Decimal("0.6")
    assert personal_a.views[0].owner_party_ids == (PARTY_A, PARTY_B)
    assert personal_b.views[0].share_for_party == Decimal("0.4")
    assert personal_a_later.views[0].share_for_party == Decimal("1")
    assert personal_b_later.views == ()
    assert household.scope == "household"
    household_ids = [view.account.account_id for view in household.views]
    assert household_ids == [ACC_IRP, ACC_UNKNOWN]
    irp_view = household.views[0]
    unknown_view = household.views[1]
    assert irp_view.share_for_party is None
    assert irp_view.owner_party_ids == (PARTY_A, PARTY_B)
    assert unknown_view.ownership_state == "unknown"
    assert unknown_view.owner_party_ids == ()
    assert ACC_UNKNOWN in household.unknown_owner_account_ids
    assert ACC_UNKNOWN not in [view.account.account_id for view in personal_a.views]


def test_post_baseline_correction_records_before_after_reason_and_reverses() -> None:
    """Meaning corrections after baseline store before/after and can be reversed."""
    registry = _seed_identities(AccountRegistry())
    with pytest.raises(Exception, match="recorded baseline"):
        registry.apply_changeset(
            SemanticChangeset(
                changeset_id=CHANGESET_OWN,
                changeset_type="ownership_correction",
                reason="too early",
                snapshot=CorrectionSnapshot(
                    before={
                        "account_id": ACC_IRP,
                        "ownership_state": "unknown",
                        "shares": [],
                    },
                    after={
                        "account_id": ACC_IRP,
                        "ownership_state": "asserted",
                        "shares": [
                            {
                                "account_id": ACC_IRP,
                                "party_id": PARTY_A,
                                "share": "1",
                                "start": "2024-01-01",
                                "end": None,
                                "confirmation_state": "confirmed",
                            }
                        ],
                    },
                ),
            )
        )
    registry.mark_baseline()
    before = {
        "account_id": ACC_IRP,
        "ownership_state": "unknown",
        "shares": [],
    }
    after = {
        "account_id": ACC_IRP,
        "ownership_state": "asserted",
        "shares": [
            {
                "account_id": ACC_IRP,
                "party_id": PARTY_A,
                "share": "1",
                "start": "2024-01-01",
                "end": None,
                "confirmation_state": "confirmed",
            }
        ],
    }
    applied = registry.apply_changeset(
        SemanticChangeset(
            changeset_id=CHANGESET_OWN,
            changeset_type="ownership_correction",
            reason="Screenshot confirms Member-A as IRP owner.",
            snapshot=CorrectionSnapshot(before=before, after=after),
        )
    )
    replayed = registry.apply_changeset(applied)

    assert replayed is applied
    recorded = registry.changeset(CHANGESET_OWN)
    assert recorded.reason == "Screenshot confirms Member-A as IRP owner."
    assert recorded.snapshot.before["ownership_state"] == "unknown"
    assert recorded.snapshot.after["ownership_state"] == "asserted"
    assert registry.get_account(ACC_IRP).ownership_state == "asserted"
    reversal = registry.reverse_changeset(CHANGESET_OWN, "Withdraw unconfirmed mapping.")
    assert reversal.reversal_of == CHANGESET_OWN
    assert reversal.snapshot.after["ownership_state"] == "unknown"
    assert registry.get_account(ACC_IRP).ownership_state == "unknown"
    assert registry.query_personal(PARTY_A, date(2024, 6, 1)).views == ()
    assert ACC_IRP in registry.query_personal(PARTY_A, date(2024, 6, 1)).unknown_owner_account_ids
    again = registry.reverse_changeset(CHANGESET_OWN, "Withdraw unconfirmed mapping.")
    assert again.changeset_id == reversal.changeset_id


def test_account_kind_is_not_a_liquidity_or_asset_class_policy() -> None:
    """Pension/IRP nature stays separate from resource liquidity policy."""
    from finjuice.pipeline.accounts.policies import liquidity_for_account_kind

    registry = _seed_identities(AccountRegistry())
    classified = registry.classify_resource(
        AssetClassification(
            resource_id=RES_FUND,
            asset_class="fund.v1",
            liquidity_policy="restricted.v1",
        )
    )

    assert registry.get_account(ACC_IRP).account_kind == "irp.v1"
    assert classified.liquidity_policy == "restricted.v1"
    assert liquidity_for_account_kind("irp.v1") is None
    assert liquidity_for_account_kind("pension.v1") is None
    assert registry.classification_for(RES_FUND) is classified
    fund_class = registry.classification_for(RES_FUND)
    assert fund_class is not None
    assert fund_class.asset_class != registry.get_account(ACC_IRP).account_kind


def test_overlapping_party_shares_are_rejected() -> None:
    """Ambiguous overlapping shares for one party cannot be asserted."""
    registry = _seed_identities(AccountRegistry())
    registry.mark_baseline()
    shares = [
        {
            "account_id": ACC_IRP,
            "party_id": PARTY_A,
            "share": "1",
            "start": "2024-01-01",
            "end": "2025-01-01",
            "confirmation_state": "confirmed",
        },
        {
            "account_id": ACC_IRP,
            "party_id": PARTY_A,
            "share": "1",
            "start": "2024-06-01",
            "end": None,
            "confirmation_state": "confirmed",
        },
    ]

    with pytest.raises(Exception, match="overlap"):
        registry.apply_changeset(
            SemanticChangeset(
                changeset_id=CHANGESET_OWN,
                changeset_type="ownership_correction",
                reason="invalid overlap",
                snapshot=CorrectionSnapshot(
                    before={
                        "account_id": ACC_IRP,
                        "ownership_state": "unknown",
                        "shares": [],
                    },
                    after={
                        "account_id": ACC_IRP,
                        "ownership_state": "asserted",
                        "shares": shares,
                    },
                ),
            )
        )


def test_register_and_alias_bind_are_idempotent() -> None:
    """Repeat registration and alias bind keep the same identity."""
    registry = _seed_identities(AccountRegistry())
    party = Party(party_id=PARTY_A, party_kind="person", display_name="Member-A")
    account = Account(account_id=ACC_IRP, account_kind="irp.v1", display_name="Broker IRP")
    alias = SourceAlias(
        entity_id=ACC_IRP,
        source_kind="banksalad",
        source_label="Broker IRP",
        confirmed=True,
    )

    assert registry.register_party(party).party_id == PARTY_A
    assert registry.register_account(account).account_id == ACC_IRP
    assert registry.bind_alias(alias).entity_id == ACC_IRP
    assert registry.resolve_alias("banksalad", "Broker IRP") == ACC_IRP


def test_queries_and_snapshots_live_in_helper_modules() -> None:
    """Period checks and snapshot codecs stay out of the package barrel."""
    queries = importlib.import_module(QUERIES_MODULE)
    snapshots = importlib.import_module(SNAPSHOTS_MODULE)
    package = importlib.import_module(PACKAGE)

    assert queries.contains.__module__ == QUERIES_MODULE
    assert snapshots.share_record.__module__ == SNAPSHOTS_MODULE
    assert not hasattr(package, "contains")
    assert not hasattr(package, "share_record")
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 2, 1))
    assert queries.contains(period, date(2024, 1, 15))
    assert not queries.contains(period, date(2024, 2, 1))
    encoded = snapshots.share_record(
        OwnershipShare(
            account_id=ACC_IRP,
            party_id=PARTY_A,
            share=Decimal("1"),
            period=period,
            confirmation_state="confirmed",
        )
    )
    assert encoded["share"] == "1"
    assert snapshots.parse_share(encoded).share == Decimal("1")
    scope = HouseholdReporting(
        household_id=HOUSEHOLD,
        account_id=ACC_IRP,
        period=period,
    )
    assert snapshots.parse_scope(snapshots.scope_record(scope)) == scope
