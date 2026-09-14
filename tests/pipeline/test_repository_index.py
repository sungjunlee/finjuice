"""Canonical catalog counts preserve evidence without reading financial live files."""

from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline import index_repository as adapter
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.test_repository_context import root as _root_fixture
from tests.pipeline.test_sqlite_exact_import import _asset_book, _import, _Repo
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture
from tests.pipeline.test_sqlite_portfolio_reads import _candidate

root = _root_fixture
repo = _repo_fixture


def _collections(result: adapter.RepositoryIndexInputs) -> dict[str, adapter.FinancialCollection]:
    return {item.name: item for item in result.collections}


def test_actual_counts_and_live_poison(root: QueryRoot) -> None:
    config = Config(data_dir=root.root)
    result = adapter.collect_repository_index_inputs(config, evidence_provider=root.provider)
    assert result is not None
    counts = _collections(result)
    assert counts["transactions"].count == 2
    assert counts["rules"].count == 0 and counts["rules"].status == "empty"
    assert counts["goals"].count == 2
    assert counts["scenarios"].status == "missing" and not counts["scenarios"].exists
    for name in ("rules.yaml", "goals.yaml", "scenarios.yaml"):
        (root.root / name).write_text("PRIVATE_POISON: [")
    assert (
        adapter.collect_repository_index_inputs(config, evidence_provider=root.provider) == result
    )


def test_one_read_and_intervening_commit_pin(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = adapter.read_checkup_snapshot
    calls = []

    def read(*args, **kwargs):
        calls.append((args, kwargs))
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"PRIVATE_POISON: [", "invalid", None, "test.v1")
        )
        return snapshot

    monkeypatch.setattr(adapter, "read_checkup_snapshot", read)
    result = adapter.collect_repository_index_inputs(
        Config(data_dir=root.root), evidence_provider=root.provider
    )
    assert result is not None and _collections(result)["rules"].count == 0
    assert len(calls) == 1 and calls[0][0][1] is root.provider
    assert result.metadata["dataset_revision"] == 0
    monkeypatch.setattr(adapter, "read_checkup_snapshot", original)
    fresh = adapter.collect_repository_index_inputs(
        Config(data_dir=root.root), evidence_provider=root.provider
    )
    assert fresh is not None and _collections(fresh)["rules"].count is None
    assert fresh.metadata["dataset_revision"] == 1


@pytest.mark.parametrize("state", ["absent", "unselected", "invalid", "opaque", "syntax"])
def test_config_state_is_not_zero(root: QueryRoot, state: str) -> None:
    snapshot = adapter.read_checkup_snapshot(root.root, root.provider)
    assert snapshot is not None and snapshot.rules.head is not None
    selection = snapshot.rules
    if state in {"absent", "unselected"}:
        selection = replace(selection, head=None, selection_state=state, revisions=())
    else:
        selection = replace(
            selection,
            head=replace(
                selection.head,
                parsed_status="parsed" if state == "syntax" else state,
                content=b"PRIVATE_POISON: [",
            ),
        )
    result = _collections(adapter.index_inputs_from_snapshot(replace(snapshot, rules=selection)))[
        "rules"
    ]
    assert result.count is None
    assert result.exists is (state != "absent")
    assert result.status == ("missing" if state == "absent" else "unavailable")
    assert "PRIVATE_POISON" not in str(result)


def test_disabled_rules_and_empty_goals(root: QueryRoot) -> None:
    snapshot = adapter.read_checkup_snapshot(root.root, root.provider)
    assert snapshot is not None and snapshot.rules.head and snapshot.portfolio.goals.head
    rules = replace(
        snapshot.rules,
        head=replace(
            snapshot.rules.head,
            content=(
                b"rules:\n- name: disabled\n  enabled: false\n  match: cafe\n"
                b"  fields: [merchant_raw]\n  tags: [food]\n"
            ),
        ),
    )
    goals = replace(
        snapshot.portfolio.goals, head=replace(snapshot.portfolio.goals.head, content=b"{}")
    )
    result = _collections(
        adapter.index_inputs_from_snapshot(
            replace(snapshot, rules=rules, portfolio=replace(snapshot.portfolio, goals=goals))
        )
    )
    assert result["rules"].count == 1
    assert result["goals"].count is None and result["goals"].status == "unavailable"


def test_scope_unknown_unmaterialized_empty_and_duplicate_aliases(root: QueryRoot) -> None:
    snapshot = adapter.read_checkup_snapshot(root.root, root.provider)
    assert snapshot is not None
    tx = snapshot.status.transactions
    cases = [
        (replace(tx, scopes=()), None),
        (replace(tx, unmaterialized_months=("2026-08",)), None),
        (replace(tx, rows=(), scopes=()), 0),
        (replace(tx, rows=tuple({**r, "row_hash": "same"} for r in tx.rows)), 2),
        (replace(tx, scopes=tuple(replace(s, month=None) for s in tx.scopes)), 2),
        (replace(tx, scopes=(replace(tx.scopes[0], included=False), *tx.scopes[1:])), 1),
    ]
    for changed, count in cases:
        result = adapter.index_inputs_from_snapshot(
            replace(snapshot, status=replace(snapshot.status, transactions=changed))
        )
        assert _collections(result)["transactions"].count == count
        assert _collections(result)["transactions"].exists


def test_asset_scope_opaque_and_overflow_count(tmp_path: Path) -> None:
    with RepositoryReader(
        _candidate(tmp_path, extra_root=True), expected_schema_version=5
    ) as reader:
        snapshot = reader.checkup_snapshot()
    initial = _collections(adapter.index_inputs_from_snapshot(snapshot))
    assert initial["assets"].count == 1  # auxiliary, empty partition, balances not counted
    evidence = {
        **snapshot.portfolio.evidence,
        "exact_values": tuple(
            {**row, "coefficient": "9" * 400} for row in snapshot.portfolio.evidence["exact_values"]
        ),
    }
    huge = replace(snapshot, portfolio=replace(snapshot.portfolio, evidence=evidence))
    assert _collections(adapter.index_inputs_from_snapshot(huge))["assets"].count == 1
    opaque = replace(snapshot, portfolio=replace(snapshot.portfolio, asset_snapshots=()))
    assert _collections(adapter.index_inputs_from_snapshot(opaque))["assets"].count is None


def test_authority_failure_is_static_and_legacy_only_none(root: QueryRoot, tmp_path: Path) -> None:
    with pytest.raises(adapter.RepositoryIndexError) as error:
        adapter.collect_repository_index_inputs(Config(data_dir=root.root))
    assert "PRIVATE" not in str(error.value)
    assert adapter.collect_repository_index_inputs(Config(data_dir=tmp_path / "legacy")) is None


def test_native_asset_dates_and_balance_independence(repo: _Repo) -> None:
    _import(repo, _asset_book(), key="asset", revision=0)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.checkup_snapshot()
    assert _collections(adapter.index_inputs_from_snapshot(snapshot))["assets"].count == 1
    rows = tuple({**row, "snapshot_date": "unknown"} for row in snapshot.portfolio.asset_snapshots)
    unknown = replace(snapshot, portfolio=replace(snapshot.portfolio, asset_snapshots=rows))
    assert _collections(adapter.index_inputs_from_snapshot(unknown))["assets"].count is None
