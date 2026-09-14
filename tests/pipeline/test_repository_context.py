"""Current context sections share detached canonical financial inputs."""

import builtins
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline import context_repository as adapter
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions

GOALS = (
    b"version: 1\nmonthly_budget:\n  total: 1800000\n  categories: {food: 600000}\n"
    b"financial_context:\n  income:\n    monthly_estimate: 5000000\n"
)


@pytest.fixture
def root(tmp_path: Path) -> QueryRoot:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(b"rules: []\n")
    (source / "goals.yaml").write_bytes(GOALS)
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row("2026-08-01", -20, "Cafe", category_final="food", tags_final="[]"),
            _tx_row("2026-08-02", -30, "Cafe", category_final="food", tags_final="[]"),
        ],
    )
    return _activate(source, tmp_path)


def test_actual_summary_and_live_poison(root: QueryRoot) -> None:
    config = Config(data_dir=root.root)
    initial = adapter.collect_repository_context_inputs(config, evidence_provider=root.provider)
    assert initial is not None
    assert initial.active_goals and "1,800,000" in initial.active_goals[0]
    assert initial.status_snapshot["active_goals"] == initial.active_goals
    assert initial.metadata["goals_state"] == "valid"
    assert initial.financial_metadata is not None
    assert initial.financial_metadata["financial_context"]["income"]["monthly_estimate"] == 5000000
    assert initial.metadata["dataset_revision"] == 0
    (root.root / "goals.yaml").write_bytes(b"PRIVATE_POISON: [")
    (root.root / "rules.yaml").write_bytes(b"PRIVATE_POISON: [")
    write_transactions(
        root.root,
        "2026-08",
        [_tx_row("2026-08-01", -999, "Poison", category_final="food", tags_final="[]")],
    )
    assert (
        adapter.collect_repository_context_inputs(config, evidence_provider=root.provider)
        == initial
    )


def test_one_read_one_frame_and_revision_pin(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    read, frame = adapter.read_analysis_source, adapter.analysis_frame
    reads, frames = [], []

    def tracked_read(*args):
        reads.append(args)
        snapshot = read(*args)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("goals", b"PRIVATE_POISON: [", "invalid", None, "test.v1")
        )
        return snapshot

    def tracked_frame(*args, **kwargs):
        frames.append(args)
        return frame(*args, **kwargs)

    monkeypatch.setattr(adapter, "read_analysis_source", tracked_read)
    monkeypatch.setattr(adapter, "analysis_frame", tracked_frame)
    result = adapter.collect_repository_context_inputs(
        Config(data_dir=root.root), evidence_provider=root.provider
    )
    assert result is not None and result.active_goals
    assert result.metadata["dataset_revision"] == 0
    assert len(reads) == len(frames) == 1
    assert reads[0][1] is root.provider
    monkeypatch.setattr(adapter, "read_analysis_source", read)
    fresh = adapter.collect_repository_context_inputs(
        Config(data_dir=root.root), evidence_provider=root.provider
    )
    assert fresh is not None and fresh.active_goals is None
    assert fresh.metadata["dataset_revision"] == 1


@pytest.mark.parametrize("state", ["absent", "unselected", "invalid", "semantic_invalid"])
def test_goals_absence_and_unknown_are_distinct(root: QueryRoot, state: str) -> None:
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None and snapshot.goals.head is not None
    if state in {"absent", "unselected"}:
        goals = replace(snapshot.goals, head=None, selection_state=state, revisions=())
    else:
        head = replace(
            snapshot.goals.head,
            content=b"monthly_budget: {total: -1}" if state == "semantic_invalid" else GOALS,
            parsed_status="parsed" if state == "semantic_invalid" else "invalid",
        )
        goals = replace(snapshot.goals, head=head)
    result = adapter.context_inputs_from_analysis(replace(snapshot, goals=goals))
    if state == "absent":
        assert result.active_goals == [] and result.financial_metadata == {}
        assert result.metadata["goals_state"] == "absent"
    else:
        assert result.active_goals is None and result.financial_metadata is None
        assert result.warnings
        assert all(result.status_snapshot[field] is None for field in adapter._GOALS_FIELDS)


@pytest.mark.parametrize("state", ["unselected", "invalid", "syntax"])
def test_rules_require_selected_valid_bytes(root: QueryRoot, state: str) -> None:
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None and snapshot.rules.head is not None
    rules = snapshot.rules
    if state == "unselected":
        rules = replace(rules, head=None, selection_state="unselected")
    else:
        rules = replace(
            rules,
            head=replace(
                rules.head,
                content=b"PRIVATE_POISON: [" if state == "syntax" else b"rules: []",
                parsed_status="parsed" if state == "syntax" else "invalid",
            ),
        )
    with pytest.raises(adapter.RepositoryContextError, match="^Canonical context could not read"):
        adapter.context_inputs_from_analysis(replace(snapshot, rules=rules))


def test_only_optional_import_absence_is_unavailable(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("PRIVATE_POISON")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    result = adapter.context_inputs_from_analysis(snapshot)
    assert result.top_patterns is None and result.active_goals
    assert result.metadata["top_patterns_state"] == "unavailable"
    assert "PRIVATE_POISON" not in str(result.warnings)


@pytest.mark.parametrize("failure", ["query", "import_in_query", "nonfinite"])
def test_query_errors_fail_whole_bundle_and_close_connection(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import duckdb

    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    connections = []

    def broken(conn, **kwargs):
        connections.append(conn)
        if failure == "nonfinite":
            return [{"delta": float("inf")}]
        error = ImportError if failure == "import_in_query" else ValueError
        raise error("PRIVATE_POISON")

    monkeypatch.setattr(adapter, "top_patterns_from_connection", broken)
    with pytest.raises(adapter.RepositoryContextError) as caught:
        adapter.context_inputs_from_analysis(snapshot)
    assert "PRIVATE_POISON" not in str(caught.value)
    with pytest.raises(duckdb.ConnectionException):
        connections[0].execute("SELECT 1")


def test_patterns_use_filtered_spend_date_and_previous_thirty_days(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(
        b"rules: []\nreport_filters:\n  excluded_categories:\n  - name: omitted\n    reason: test\n"
    )
    rows = [
        _tx_row(day, amount, label, category_final=label, tags_final="[]", is_transfer=transfer)
        for day, amount, label, transfer in [
            ("2026-06-30", -900, "food", 0),
            ("2026-07-15", -20, "food", 0),
            ("2026-08-15", -70, "food", 0),
            ("2026-08-30", -30, "food", 0),
            ("2026-12-01", -999, "omitted", 0),
            ("2026-12-02", -999, "transfer", 1),
            ("2026-12-03", 999, "income", 0),
        ]
    ]
    rows[5]["transfer_group_id"] = "confirmed-transfer"
    write_transactions(source, "2026-08", rows)
    root = _activate(source, tmp_path)
    result = adapter.collect_repository_context_inputs(
        Config(data_dir=root.root), evidence_provider=root.provider
    )
    assert result is not None
    assert result.top_patterns == [{"label": "food", "delta_krw": 80, "direction": "up"}]
    assert result.metadata["rules_selection_state"] == "selected"


def test_adapter_can_import_without_optional_duckdb() -> None:
    import subprocess
    import sys

    code = """
import builtins
original = builtins.__import__
def unavailable(name, *args, **kwargs):
    if name == 'duckdb' or name.startswith('duckdb.'):
        raise ImportError('optional unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = unavailable
from finjuice.pipeline import context_repository
from pathlib import Path
import sys
assert Path(context_repository.__file__).resolve() == Path(sys.argv[1]).resolve()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, adapter.__file__],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_empty_is_not_incomplete(root: QueryRoot) -> None:
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    empty = replace(snapshot.transactions, rows=(), scopes=(), partition_months=())
    result = adapter.context_inputs_from_analysis(replace(snapshot, transactions=empty))
    assert result.top_patterns == []
    assert result.active_goals
    incomplete = replace(empty, unmaterialized_months=("2026-08",))
    with pytest.raises(adapter.RepositoryContextError):
        adapter.context_inputs_from_analysis(
            replace(snapshot, transactions=incomplete, unmaterialized_months=("2026-08",))
        )
