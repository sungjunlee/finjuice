"""Portfolio snapshots preserve source evidence without live-file fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, SourceRoot, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.migration.common import canonical, seal, tree_inventory
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import MANUAL_STATE_POLICY, OVERVIEW_REPORT_POLICY
from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot
from finjuice.pipeline.storage.sqlite import (
    EntityRelationAssertionRecord,
    GenerationPaths,
    PartyRecord,
    RepositoryReader,
    new_entity_id,
    upgrade_repository,
)
from finjuice.pipeline.storage.sqlite.errors import AuthorityEvidenceUnavailableError
from finjuice.pipeline.storage.sqlite.mutations import MutationContext, MutationService
from finjuice.pipeline.storage.sqlite.portfolio_reads import _portfolio_path
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture
from tests.migration.test_overview_v4_integration import write_overview_sources
from tests.pipeline.test_sqlite_exact_import import _asset_book, _import, _overview_book, _Repo
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture
from tests.pipeline.test_sqlite_mutations import _ownership_handler, _request

query_root = _query_root_fixture
repo = _repo_fixture


def _candidate(tmp_path: Path, policy: str | None = None, *, extra_root: bool = False) -> Path:
    source = tmp_path / "source"
    write_overview_sources(source)
    assets = source / "assets/snapshots/2026/01/snapshots.csv"
    assets.parent.mkdir(parents=True)
    assets.write_text(
        "snapshot_date,account_id,instrument_id,quantity,market_value,currency\n"
        "2026-01-31,account,resource,-0.000,9007199254740993.01,\n"
    )
    empty = source / "assets/snapshots/2026/02/snapshots.csv"
    empty.parent.mkdir(parents=True)
    empty.write_text("snapshot_date,account_id,instrument_id,quantity,market_value,currency\n")
    (source / "assets.yaml").write_bytes(b"assets: [\n")
    (source / "scenarios.yaml").write_bytes(b"scenarios: {}\n")
    nested = source / "nested/assets.yaml"
    nested.parent.mkdir()
    nested.write_bytes(b"assets: []\n")
    distractor = source / "banksalad/transactions.csv"
    distractor.write_text("description_raw,amount\nprivate-row,99\n")
    extra = tmp_path / "extra"
    roots = ()
    if extra_root:
        write_overview_sources(extra)
        roots = (SourceRoot("other", "required", extra),)
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source, capture, ConsistencyEvidence("stopped_writers", ("test",)), extra_roots=roots
        )
    )
    plan_path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=plan_path, active_data_dir=source).to_dict()["plan"]
    if policy is not None:
        plan.pop("canonical_digest")
        plan["migration_policy"] = policy
        plan["inputs"] = analyze_capture(capture, plan["capture"], policy=policy)
        plan_path.write_text(canonical(seal(plan)))
    candidate = tmp_path / "candidate"
    build_migration(plan_path, candidate, active_data_dir=source)
    return candidate / "finjuice.sqlite3"


def test_actual_migration_exact_values_configs_and_detachment(tmp_path: Path) -> None:
    database = _candidate(tmp_path)
    with RepositoryReader(database) as reader:
        snapshot = reader.portfolio_snapshot()
    assert isinstance(snapshot.asset_snapshots, tuple)
    assert snapshot.assets.head is not None
    assert snapshot.assets.head.content == b"assets: [\n"
    assert snapshot.assets.head.parsed_status == "invalid"
    assert len(snapshot.assets.revisions) == 2
    assert snapshot.goals.selection_state == "absent"
    assert snapshot.scenarios.selection_state == "selected"
    exact = {row["value_id"]: row for row in snapshot.evidence["exact_values"]}
    position = snapshot.asset_snapshots[0]
    assert exact[position["market_value_id"]]["lexical"] == "9007199254740993.01"
    assert exact[position["quantity_value_id"]]["lexical"] == "-0.000"
    assert position["account_id"] != "account"
    assert snapshot.evidence["accounts"][0]["ownership_state"] == "unknown"
    assert len(snapshot.legacy_overview_reports["legacy_overview_reports"]) == 5
    assert snapshot.evidence["legacy_payloads"]
    assert any(
        row["path"] == "assets/snapshots/2026/01/snapshots.csv" for row in snapshot.source_scopes
    )
    with pytest.raises(RuntimeError, match="closed"):
        reader.portfolio_snapshot()


@pytest.mark.parametrize("policy", [MANUAL_STATE_POLICY, OVERVIEW_REPORT_POLICY])
def test_old_policies_keep_unselected_configs_and_report_support(
    tmp_path: Path, policy: str
) -> None:
    database = _candidate(tmp_path, policy)
    version = 4 if policy == MANUAL_STATE_POLICY else 5
    with RepositoryReader(database, expected_schema_version=version) as reader:
        snapshot = reader.portfolio_snapshot()
    assert snapshot.assets.selection_state == "unselected"
    assert snapshot.assets.head is None
    assert len(snapshot.assets.revisions) == 2
    assert snapshot.scenarios.selection_state == "unselected"
    if version == 4:
        assert snapshot.legacy_reports_support == "preserved_observations_only"
        assert snapshot.legacy_overview_reports == {}
        assert snapshot.evidence["observations"]
        assert snapshot.evidence["legacy_payloads"]
    else:
        assert snapshot.legacy_reports_support == "typed"


def test_authority_and_same_reader_config_revision(query_root: QueryRoot, tmp_path: Path) -> None:
    assert read_portfolio_snapshot(tmp_path / "legacy") is None
    with pytest.raises(AuthorityEvidenceUnavailableError):
        read_portfolio_snapshot(query_root.root)
    facade = StorageMutationFacade(query_root.root, query_root.provider)
    facade.replace_config(ConfigDocument("assets", b"assets: []\n", "opaque", None, "test.v1"))
    paths = AuthorityPaths.for_data_dir(query_root.root).generation(query_root.generation)
    with RepositoryReader(paths.database) as reader:
        initial = reader.portfolio_snapshot()
        facade.replace_config(ConfigDocument("assets", b"assets: {}\n", "invalid", None, "test.v1"))
        assert reader.portfolio_snapshot() == initial
    fresh = read_portfolio_snapshot(query_root.root, query_root.provider)
    assert fresh is not None and fresh.assets.head is not None
    assert fresh.info.dataset_revision == initial.info.dataset_revision + 1
    assert fresh.assets.head.parsed_status == "invalid"
    # Transaction-only source rows are outside portfolio evidence.
    assert fresh.evidence["observations"] == ()


def test_multiple_roots_reference_candidates_and_scope_exclusions(tmp_path: Path) -> None:
    with RepositoryReader(_candidate(tmp_path, extra_root=True)) as reader:
        snapshot = reader.portfolio_snapshot()
    reports = snapshot.legacy_overview_reports
    assert len(reports["legacy_overview_reports"]) == 10
    assert {row["status"] for row in reports["legacy_overview_reference_assessments"]} == {
        "missing",
        "ambiguous",
    }
    assert {row["root"] for row in snapshot.source_scopes} == {"data", "other"}
    assert all(row["path"] != "banksalad/transactions.csv" for row in snapshot.source_scopes)
    assert all(
        row["legacy_path"] != "banksalad/transactions.csv"
        for row in snapshot.evidence["source_occurrences"]
    )
    assert len({row["provenance_id"] for row in reports["legacy_overview_reports"]}) == 10
    money = {row["value_id"]: row for row in snapshot.evidence["money_values"]}
    for cashflow in reports["legacy_overview_cashflows"]:
        assert money[cashflow["amount_value_id"]]["currency_unknown"] == 1
    assert all(row["paid_amount_value_id"] is None for row in reports["legacy_overview_insurance"])


def test_native_asset_and_overview_exact_provenance(repo: _Repo) -> None:
    _import(repo, _asset_book(), key="assets", revision=0)
    _import(repo, _overview_book(), key="overview", revision=repo.revision())
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
    assert len(snapshot.asset_snapshots) == 1
    assert len(snapshot.native_overview_reports["overview_balances"]) == 1
    assert snapshot.legacy_overview_reports["legacy_overview_reports"] == ()
    provenance = {row["provenance_id"] for row in snapshot.evidence["record_provenance"]}
    assert all(row["provenance_id"] in provenance for row in snapshot.evidence["exact_values"])
    assert snapshot.evidence["legacy_payloads"]
    assert snapshot.evidence["ownership_assertion_sets"] == ()


@pytest.mark.parametrize(
    "path",
    [
        "banksalad/transactions.csv",
        "backup/banksalad/balance/2026/01/balance.csv",
        "banksalad/balance/2026/01/transactions.csv",
        "assets/snapshots/2026/13/snapshots.csv",
    ],
)
def test_nonportfolio_source_paths_are_not_scopes(path: str) -> None:
    assert not _portfolio_path(path)


def test_native_ownership_share_and_direct_relation_evidence(repo: _Repo) -> None:
    _import(repo, _asset_book(), key="assets", revision=0)
    with RepositoryReader(repo.database) as reader:
        account = reader.portfolio_snapshot().asset_snapshots[0]["account_id"]
    party, external, claim, share = (new_entity_id() for _ in range(4))
    relation, unrelated = new_entity_id(), new_entity_id()

    def add_evidence(context: MutationContext):
        context.add_party(PartyRecord(party))
        context.add_party(PartyRecord(external))
        result = _ownership_handler(
            account_id=account,
            party_id=party,
            assertion_id=claim,
            value_id=share,
            coefficient="5",
            scale=1,
            completeness="partial",
        )(context)
        for identifier, subject, target in (
            (relation, account, external),
            (unrelated, party, external),
        ):
            context.add_relation_assertion(
                EntityRelationAssertionRecord(
                    identifier,
                    subject,
                    target,
                    "unknown",
                    "unconfirmed",
                    {"kind": "synthetic"},
                )
            )
        return result

    MutationService(repo.paths, repo.evidence).execute(
        _request(repo.generation, "portfolio-ownership", repo.revision()), add_evidence
    )
    with RepositoryReader(repo.database) as reader:
        evidence = reader.portfolio_snapshot().evidence
    assert evidence["ownership_assertion_sets"][0]["assertion_id"] == claim
    assert evidence["ownership_assertion_shares"][0]["share_value_id"] == share
    assert {row["entity_id"] for row in evidence["parties"]} == {party}
    value = next(row for row in evidence["exact_values"] if row["value_id"] == share)
    assert (value["coefficient"], value["scale"]) == ("5", 1)
    assert (
        next(row for row in evidence["rate_values"] if row["value_id"] == share)["unit"]
        == "ownership_share.v1"
    )
    assert {row["assertion_id"] for row in evidence["entity_relation_assertions"]} == {relation}
    assert evidence["entity_relation_assertions"][0]["object_entity_id"] == external


def test_upgrade_capability_does_not_claim_preserved_reports_were_materialized(
    tmp_path: Path,
) -> None:
    database = _candidate(tmp_path, MANUAL_STATE_POLICY)
    original_inventory = tree_inventory(database.parent)
    target = GenerationPaths(tmp_path / "upgraded")

    upgrade_repository(database, target)
    with RepositoryReader(target.database) as reader:
        snapshot = reader.portfolio_snapshot()

    assert snapshot.legacy_reports_support == "typed"
    assert snapshot.legacy_overview_reports["legacy_overview_reports"] == ()
    assert snapshot.evidence["observations"]
    assert snapshot.evidence["legacy_payloads"]
    assert any(scope["path"].endswith("balance.csv") for scope in snapshot.source_scopes)
    assert snapshot.assets.selection_state == "unselected"
    assert tree_inventory(database.parent) == original_inventory
