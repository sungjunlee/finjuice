"""Repository suggestions use a single detached canonical baseline."""

from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.tagging import suggestion_repository as adapter
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions

OPTIONS = adapter.SuggestionReadOptions()


@pytest.fixture
def root(tmp_path: Path) -> QueryRoot:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(b"rules: []\n")
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row("2026-08-01", -20, "Coffee Garden", category_final="food", tags_final="[]"),
            _tx_row("2026-08-02", -30, "Coffee Garden", category_final="food", tags_final="[]"),
        ],
    )
    return _activate(source, tmp_path)


def test_live_poison_does_not_change_calculation(root: QueryRoot) -> None:
    initial = adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)
    assert initial is not None and initial.stats["total_count"] == 2
    (root.root / "rules.yaml").write_bytes(b"PRIVATE_POISON: [")
    write_transactions(
        root.root,
        "2026-08",
        [_tx_row("2026-08-01", -999, "PRIVATE_POISON", category_final="food", tags_final="[]")],
    )
    assert adapter.read_repository_suggestions(root.root, root.provider, OPTIONS) == initial


def test_one_read_and_same_connection_survive_intervening_commit(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = adapter.read_analysis_source
    coverage = adapter.coverage_stats_from_connection
    context = adapter.merchant_context_from_connection
    reads, connections = [], []

    def tracked_read(*args):
        reads.append(args)
        return read(*args)

    def stats(conn, file_id):
        connections.append(conn)
        result = coverage(conn, file_id)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument(
                "rules",
                b"rules:\n- name: coffee\n  match: Coffee Garden\n"
                b"  fields: [merchant_raw]\n  tags: [food]\n",
                "parsed",
                None,
                "test.v1",
            )
        )
        return result

    def contexts(conn, *args):
        assert conn is connections[0]
        return context(conn, *args)

    monkeypatch.setattr(adapter, "read_analysis_source", tracked_read)
    monkeypatch.setattr(adapter, "coverage_stats_from_connection", stats)
    monkeypatch.setattr(adapter, "merchant_context_from_connection", contexts)
    result = adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)
    assert result is not None and result.metadata["dataset_revision"] == 0
    assert result.suggestions and len(reads) == 1
    monkeypatch.setattr(adapter, "coverage_stats_from_connection", coverage)
    monkeypatch.setattr(adapter, "merchant_context_from_connection", context)
    fresh = adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)
    assert fresh is not None and fresh.metadata["dataset_revision"] == 1
    assert fresh.suggestions == []
    import duckdb

    with pytest.raises(duckdb.ConnectionException):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize(
    "status,content",
    [
        ("invalid", b"rules: []"),
        ("opaque", b"rules: []"),
        ("parsed", b"PRIVATE_POISON: ["),
        ("parsed", b"rules: [PRIVATE_POISON]"),
    ],
)
def test_invalid_selection_is_static(
    root: QueryRoot, status: str, content: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", content, status, None, "test.v1")
    )
    (root.root / "rules.yaml").write_bytes(b"rules: []")
    with pytest.raises(ValueError, match="^Canonical suggestions could not be evaluated.$"):
        adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)
    assert "PRIVATE_POISON" not in caplog.text


def test_absent_is_allowed_but_unselected_is_not(root: QueryRoot) -> None:
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    absent = replace(snapshot.rules, head=None, revisions=(), selection_state="absent")
    assert adapter.suggestions_from_snapshot(replace(snapshot, rules=absent), OPTIONS).suggestions
    unselected = replace(snapshot.rules, head=None, selection_state="unselected")
    with pytest.raises(ValueError, match="valid selected configuration"):
        adapter.suggestions_from_snapshot(replace(snapshot, rules=unselected), OPTIONS)


def test_primary_opaque_is_not_zero_success(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    write_transactions(
        source,
        "2026-08",
        [_tx_row("2026-08-01", -20, "PRIVATE_POISON", category_final="food", tags_final="broken[")],
    )
    root = _activate(source, tmp_path)
    with pytest.raises(ValueError, match="^Canonical suggestions could not be evaluated.$"):
        adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)


@pytest.mark.parametrize("failure", ["registration", "query", "nonfinite"])
def test_connection_closed_and_failure_private(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import duckdb

    original = adapter.register_transaction_frame
    connections = []

    def register(conn, *args):
        connections.append(conn)
        if failure == "registration":
            raise ValueError("PRIVATE_POISON")
        original(conn, *args)

    def contexts(*args):
        if failure == "query":
            raise ValueError("PRIVATE_POISON")
        return [{"amount": float("inf")}], []

    monkeypatch.setattr(adapter, "register_transaction_frame", register)
    monkeypatch.setattr(adapter, "merchant_context_from_connection", contexts)
    with pytest.raises(ValueError, match="^Canonical suggestions could not be evaluated.$"):
        adapter.read_repository_suggestions(root.root, root.provider, OPTIONS)
    assert len(connections) == 1
    with pytest.raises(duckdb.ConnectionException):
        connections[0].execute("SELECT 1")


def test_actual_absent_empty_repository(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    write_transactions(
        source,
        "2026-08",
        [_tx_row("2026-08-01", -20, "Coffee Garden", category_final="food", tags_final="[]")],
    )
    partition = source / "transactions/2026/08/transactions.csv"
    partition.write_text(partition.read_text().splitlines()[0] + "\n")
    root = _activate(source, tmp_path)
    snapshot = adapter.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    result = adapter.suggestions_from_snapshot(snapshot, OPTIONS)
    assert result.stats["total_count"] == 0 and result.suggestions == []
    assert result.metadata["rules_selection_state"] == "absent"
    assert result.metadata["rules_revision_id"] is None


def test_authority_missing_fails_statically(root: QueryRoot) -> None:
    with pytest.raises(ValueError, match="^Canonical suggestions could not be evaluated.$"):
        adapter.read_repository_suggestions(root.root, None, OPTIONS)
