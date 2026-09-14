"""Analysis inputs preserve authority, config selection, and one reader revision."""

from __future__ import annotations

from pathlib import Path

import pytest

from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_analysis_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import AuthorityEvidenceUnavailableError
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture

query_root = _query_root_fixture


def test_writer_between_transactions_and_configs_keeps_revision(
    query_root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = read_analysis_snapshot(query_root.root, query_root.provider)
    assert before is not None
    original = RepositoryReader.transaction_snapshot

    def mutate_after_transactions(reader: RepositoryReader):
        transactions = original(reader)
        StorageMutationFacade(query_root.root, query_root.provider).replace_config(
            ConfigDocument("goals", b"goals: []\n", "opaque", None, "test.v1")
        )
        return transactions

    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", mutate_after_transactions)
    assert read_analysis_snapshot(query_root.root, query_root.provider) == before
    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", original)
    fresh = read_analysis_snapshot(query_root.root, query_root.provider)
    assert fresh is not None and fresh.goals.head is not None
    assert fresh.info.dataset_revision == before.info.dataset_revision + 1
    assert fresh.goals.head.parsed_status == "opaque"
    assert fresh.info == fresh.transactions.info


def test_nested_payloads_are_owned_and_no_unneeded_domain_reads(
    query_root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Unneeded portfolio/import domain was loaded")

    monkeypatch.setattr(RepositoryReader, "portfolio_snapshot", forbidden)
    monkeypatch.setattr(RepositoryReader, "checkup_snapshot", forbidden)
    monkeypatch.setattr(
        "finjuice.pipeline.storage.sqlite.exact_import.lookup.load_transaction_identity_snapshot",
        forbidden,
    )
    snapshot = read_analysis_snapshot(query_root.root, query_root.provider)
    assert snapshot is not None
    assert snapshot.rules.head is not None
    assert snapshot.rules.head.content == snapshot.transactions.rules_content
    snapshot.transactions.rows[0]["notes_manual"] = "caller-owned"
    snapshot.rules.revisions[0]["canonical_payload_json"] = "caller-owned"
    assert read_analysis_snapshot(query_root.root, query_root.provider) != snapshot


@pytest.mark.parametrize("nested", [False, True])
def test_missing_head_distinguishes_unselected_revisions(tmp_path: Path, nested: bool) -> None:
    source = tmp_path / "source"
    source.mkdir()
    if nested:
        target = source / "nested/rules.yaml"
        target.parent.mkdir()
        target.write_text("version: 1\nrules: []\n")
    root = _activate(source, tmp_path)
    snapshot = read_analysis_snapshot(root.root, root.provider)
    assert snapshot is not None and snapshot.rules.head is None
    assert snapshot.rules.selection_state == ("unselected" if nested else "absent")
    assert bool(snapshot.rules.revisions) is nested
    assert snapshot.goals.selection_state == "absent"


def test_authority_and_closed_reader(query_root: QueryRoot, tmp_path: Path) -> None:
    from finjuice.pipeline.storage.authority import AuthorityPaths

    assert read_analysis_snapshot(tmp_path / "legacy") is None
    with pytest.raises(AuthorityEvidenceUnavailableError):
        read_analysis_snapshot(query_root.root)
    database = (
        AuthorityPaths.for_data_dir(query_root.root).generation(query_root.generation).database
    )
    with RepositoryReader(database) as reader:
        snapshot = reader.analysis_snapshot()
    assert snapshot.transactions.rows
    with pytest.raises(RuntimeError, match="closed"):
        reader.analysis_snapshot()


@pytest.mark.parametrize("damage", ["tags", "duplicate_header", "invalid_utf8", "missing_header"])
def test_unmaterialized_primary_rows_and_file_failures_are_not_empty(
    tmp_path: Path, damage: str
) -> None:
    import csv
    import io

    from finjuice.pipeline.backup import (
        ConsistencyEvidence,
        CreateRequest,
        SourceRoot,
        create_backup,
    )
    from finjuice.pipeline.migration import build_migration, plan_migration
    from tests.pipeline.checkup.helpers import _tx_row

    source, auxiliary = tmp_path / "source", tmp_path / "auxiliary"
    row = _tx_row("2026-01-01", -100, "synthetic", category_final="food", tags_final="[]")

    def csv_bytes(item):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(item))
        writer.writeheader()
        writer.writerow(item)
        return stream.getvalue().encode()

    valid = csv_bytes(row)
    malformed = {
        "tags": csv_bytes({**row, "tags_final": "not-json"}),
        "duplicate_header": b"amount,amount\n1,2\n",
        "invalid_utf8": b"\xff\xfe",
        "missing_header": b"",
    }[damage]
    for root, month, content in (
        (source, "01", malformed),
        (source, "02", valid.splitlines(keepends=True)[0]),
        (source, "03", valid),
        (auxiliary, "04", malformed),
    ):
        target = root / f"transactions/2026/{month}/transactions.csv"
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("test",)),
            extra_roots=(SourceRoot("other", "required", auxiliary),),
        )
    )
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        snapshot = reader.analysis_snapshot()
    assert snapshot.unmaterialized_months == ("2026-01",)
    assert snapshot.transactions.unmaterialized_months == snapshot.unmaterialized_months
    from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
    from finjuice.pipeline.storage.sqlite.transaction_completeness import (
        require_transaction_completeness,
    )

    with pytest.raises(RepositoryIntegrityError, match="lack typed read values"):
        require_transaction_completeness(snapshot.transactions)
    with pytest.raises(RepositoryIntegrityError):
        require_transaction_completeness(snapshot.transactions, month="2026-01")
    require_transaction_completeness(snapshot.transactions, month="2026-02")
    require_transaction_completeness(snapshot.transactions, month="2026-03")
    require_transaction_completeness(snapshot.transactions, month="2026-04")
    assert len(snapshot.transactions.rows) == 1
    assert snapshot.transactions.partition_months == ("2026-01", "2026-02", "2026-03")
