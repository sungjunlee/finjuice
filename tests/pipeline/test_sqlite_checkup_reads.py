"""One revision binds checkup domains and pure captured import previews."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityEvidenceUnavailableError,
    MutationConflictError,
    MutationValidationError,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import (
    ExactImportCommand,
    ExactImportIntent,
)
from finjuice.pipeline.storage.sqlite.exact_import.preview import preview_captured_import
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture
from tests.pipeline.test_sqlite_exact_import import _capture, _import, _Repo, _tx_book, _tx_row
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture
from tests.pipeline.test_sqlite_exact_import_contract import _manifest

repo = _repo_fixture
query_root = _query_root_fixture


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_pinned_preview_then_new_import_and_fresh_noop(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    capture = _capture(data)
    command = ExactImportCommand(capture, preview=True)
    generation = repo.database.parent
    original = _files(generation)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.checkup_snapshot((capture.digest_hex,))
        assert (
            snapshot.info
            == snapshot.status.info
            == snapshot.portfolio.info
            == snapshot.imports.info
        )
        assert snapshot.rules.selection_state == "absent"
        assert snapshot.rules.revisions == ()
        assert snapshot.imports.completed_by_digest == {capture.digest_hex: ()}
        outcome = preview_captured_import(command, snapshot.imports)
        assert outcome.result["counts"]["transactions"]["inserted"] == 1
        assert _files(generation) == original
        _import(repo, data, key="first", revision=0)
        assert reader.checkup_snapshot((capture.digest_hex,)) == snapshot
        assert preview_captured_import(command, snapshot.imports) == outcome
    with RepositoryReader(repo.database) as fresh:
        current = fresh.checkup_snapshot((capture.digest_hex,))
        before = _files(generation)
        noop = preview_captured_import(command, current.imports)
        assert noop.result["noop"] is True
        assert current.info.dataset_revision == 1
        assert current.imports.transaction_identities
        assert _files(generation) == before
        # Returned nested payload changes must not leak into this reader or future DTOs.
        record = current.imports.completed_by_digest[capture.digest_hex][0]
        record["payload"]["counts"]["transactions"]["inserted"] = 999
        assert fresh.checkup_snapshot((capture.digest_hex,)).imports != current.imports
    with pytest.raises(RuntimeError, match="closed"):
        reader.checkup_snapshot()


def test_unrequested_digest_and_nonpreview_intent_are_not_absence(repo: _Repo) -> None:
    capture = _capture(_tx_book(_tx_row(2)))
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.checkup_snapshot()
    with pytest.raises(MutationValidationError, match="not requested"):
        preview_captured_import(ExactImportCommand(capture, preview=True), snapshot.imports)
    with pytest.raises(MutationValidationError, match="preview intent"):
        preview_captured_import(ExactImportCommand(capture), snapshot.imports)


def test_completed_changed_intent_and_malformed_closure_fail(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    capture = _capture(data)
    _import(repo, data, key="first", revision=0)
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.checkup_snapshot((capture.digest_hex,))
    changed = ExactImportCommand(
        capture, ExactImportIntent(transaction_sheet="different"), preview=True
    )
    with pytest.raises(MutationConflictError):
        preview_captured_import(changed, snapshot.imports)
    provenance, payload = _manifest(repo)
    payload["counts"]["transactions"]["inserted"] = 999
    with sqlite3.connect(repo.database) as connection:
        connection.execute("DROP TRIGGER legacy_payloads_no_update")
        connection.execute(
            "UPDATE legacy_payloads SET payload_json = ? WHERE provenance_id = ?",
            (json.dumps(payload), provenance),
        )
    with RepositoryReader(repo.database) as reader:
        with pytest.raises(MutationValidationError):
            reader.checkup_snapshot((capture.digest_hex,))


def test_facade_authority_and_nested_domains_detach(query_root: QueryRoot, tmp_path: Path) -> None:
    assert read_checkup_snapshot(tmp_path / "legacy") is None
    with pytest.raises(AuthorityEvidenceUnavailableError):
        read_checkup_snapshot(query_root.root)
    snapshot = read_checkup_snapshot(query_root.root, query_root.provider)
    assert snapshot is not None
    assert snapshot.rules.selection_state == "selected"
    assert snapshot.rules.head == snapshot.status.rules
    first = snapshot.status.transactions.rows[0]
    first["notes_manual"] = "caller-owned"
    assert read_checkup_snapshot(query_root.root, query_root.provider) != snapshot
    assert replace(snapshot, imports=snapshot.imports).info == snapshot.portfolio.info


def test_writer_between_domains_does_not_split_revision(
    query_root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade

    before = read_checkup_snapshot(query_root.root, query_root.provider)
    assert before is not None
    original = RepositoryReader.portfolio_snapshot

    def mutate_then_read(reader: RepositoryReader):
        StorageMutationFacade(query_root.root, query_root.provider).replace_config(
            ConfigDocument("goals", b"goals: []\n", "opaque", None, "test.v1")
        )
        return original(reader)

    monkeypatch.setattr(RepositoryReader, "portfolio_snapshot", mutate_then_read)
    pinned = read_checkup_snapshot(query_root.root, query_root.provider)
    assert pinned == before
    monkeypatch.setattr(RepositoryReader, "portfolio_snapshot", original)
    fresh = read_checkup_snapshot(query_root.root, query_root.provider)
    assert fresh is not None
    assert fresh.info.dataset_revision == before.info.dataset_revision + 1
    assert fresh.portfolio.goals.head == fresh.status.goals
    assert fresh.portfolio.goals.head is not None


def test_statement_capture_and_pinned_preview_do_not_reopen_source(
    repo: _Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.checkup.import_preview import (
        capture_staged_imports,
        summarize_staged_imports,
    )
    from finjuice.pipeline.statements import staged
    from finjuice.pipeline.statements.canonical import StatementImport
    from tests.pipeline.test_canonical_statement_json import _envelope, _record

    imports = tmp_path / "staged"
    imports.mkdir()
    path = imports / "statement.json"
    content = json.dumps(_envelope([_record("captured-once")])).encode()
    path.write_bytes(content)
    reads = []
    original_read = staged.read_regular_bytes

    def capture_once(source: Path) -> bytes:
        reads.append(source.name)
        result = original_read(source)
        source.write_bytes(b"now malformed")
        return result

    monkeypatch.setattr(staged, "read_regular_bytes", capture_once)
    observed = capture_staged_imports(imports)
    assert reads == ["statement.json"]
    assert observed.statements[0].content == content
    statements = tuple(item.content for item in observed.statements)
    with RepositoryReader(repo.database) as reader:
        pinned = reader.checkup_snapshot(observed.digests, statements=statements)
        assert summarize_staged_imports(observed, pinned.imports).pending_files == 1
        repo.facade.import_statement(
            StatementImport(content, imported_at="2026-09-15T00:00:00Z"),
            identity=repo.identity("statement-first", 0),
        )
        assert reader.checkup_snapshot(observed.digests, statements=statements) == pinned
    with RepositoryReader(repo.database) as reader:
        fresh = reader.checkup_snapshot(observed.digests, statements=statements)
    assert summarize_staged_imports(observed, fresh.imports).pending_files == 0
    assert summarize_staged_imports(observed, pinned.imports).pending_files == 1
    assert reads == ["statement.json"]
    with pytest.raises(MutationValidationError, match="not requested"):
        summarize_staged_imports(observed, replace(fresh.imports, statement_results={}))
