"""Restored copies use the typed writer without inventing host activation."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from finjuice.pipeline.storage.sqlite import inactive_restore as restore_module
from finjuice.pipeline.storage.sqlite import inactive_restore_descriptor as descriptor_module
from finjuice.pipeline.storage.sqlite import mutations as mutation_module
from finjuice.pipeline.storage.sqlite.backup import backup_status, create_backup
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, RepositoryPathError
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreError,
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.mutations import (
    ManualTransactionEdit,
    MutationOutcome,
    MutationService,
)
from tests.pipeline.test_sqlite_mutations import _active_repository_with_transactions, _request


def _prepare(tmp_path: Path):
    paths, _, generation, transactions, _ = _active_repository_with_transactions(
        tmp_path / "source"
    )
    backup = tmp_path / "backup"
    create_backup(paths.generation(generation).database, backup)
    receipt = restore_workspace(backup, tmp_path / "workspace")
    return paths, generation, transactions[0], backup, receipt


def _bytes(root: Path):
    return {
        path.relative_to(root).as_posix(): (path.stat().st_ino, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def _manual(transaction: str, note: str = "restored note"):
    def handler(context):
        assert not hasattr(context.authority, "activation")
        return MutationOutcome(
            result=context.edit_manual_transaction(
                ManualTransactionEdit(
                    identifier=transaction,
                    note_supplied=True,
                    note=note,
                    category_supplied=True,
                    category="Travel",
                )
            )
        )

    return handler


def test_restored_manual_edit_read_replay_and_rebackup_preserve_source(tmp_path):
    _, generation, transaction, backup, receipt = _prepare(tmp_path)
    original = _bytes(tmp_path / "source")
    original_backup = _bytes(backup)
    request = _request(generation, "restored-manual", 0, scope="transaction.manual_edit")

    with InactiveRestoreSession(receipt) as session:
        before = session.read_snapshot(lambda reader: reader.rows("transactions"))
        first = session.execute(request, _manual(transaction))
        assert first.committed_revision == 1
        assert first.result["confidence_exact"] == "1"
        replay = session.execute(request, lambda _: pytest.fail("replay invoked handler"))
        assert replay.replayed and replay.changeset_id == first.changeset_id
        assert session.find_replay(request).changeset_id == first.changeset_id
        after = session.read_snapshot(lambda reader: reader.rows("transactions"))
        assert after[0]["notes_manual"] == "restored note"
        assert after[0]["category_manual"] == "Travel"
        assert after[0]["amount_value_id"] == before[0]["amount_value_id"]
        assert session.read_snapshot(lambda reader: len(reader.rows("changesets"))) == 1
        assert session.read_snapshot(lambda reader: len(reader.rows("audit_events"))) > 0
        assert session.preview(
            _request(generation, "preview", 1), lambda _: MutationOutcome(result={"ready": True})
        ) == {"ready": True}
        with pytest.raises(MutationConflictError):
            session.execute(_request(generation, "stale", 0), _manual(transaction, "wrong"))
        second = session.backup(tmp_path / "second-backup")
        assert second.dataset_revision == 1

    with InactiveRestoreSession(receipt) as reopened:
        assert reopened.read_snapshot(lambda reader: reader.info.dataset_revision) == 1
    second_receipt = restore_workspace(tmp_path / "second-backup", tmp_path / "second-workspace")
    with InactiveRestoreSession(second_receipt) as second_session:
        assert second_session.read_snapshot(lambda reader: reader.rows("transactions")) == after
        assert second_session.read_snapshot(lambda reader: len(reader.rows("changesets"))) == 1

    assert _bytes(tmp_path / "source") == original
    assert _bytes(backup) == original_backup
    assert backup_status(backup).complete
    assert not backup_status(receipt.workspace / "generation").complete
    assert not list(receipt.workspace.rglob("active.json"))
    assert str(receipt.workspace) not in json.dumps(receipt.to_dict())
    with pytest.raises(InactiveRestoreError):
        session.read_snapshot(lambda reader: reader.info)


def test_retirement_invalidates_other_handles_and_receipt_reopen(tmp_path):
    _, generation, transaction, _, receipt = _prepare(tmp_path)
    with InactiveRestoreSession(receipt) as first, InactiveRestoreSession(receipt) as other:
        first.retire()
        with pytest.raises(InactiveRestoreError):
            other.execute(_request(generation, "after-retirement", 0), _manual(transaction))
    with pytest.raises(InactiveRestoreError), InactiveRestoreSession(receipt):
        pass


@pytest.mark.parametrize("tamper", ["duplicate", "changed", "receipt"])
def test_descriptor_requires_exact_receipt_and_json(tmp_path, tamper):
    _, _, _, _, receipt = _prepare(tmp_path)
    path = receipt.workspace / "restore-control" / "descriptor.json"
    raw = path.read_text()
    if tamper == "duplicate":
        key, value = next(iter(json.loads(raw).items()))
        path.write_text("{" + json.dumps(key) + ":" + json.dumps(value) + "," + raw[1:])
    elif tamper == "changed":
        path.write_text(raw.replace(receipt.restore_id, "0" * len(receipt.restore_id)))
    else:
        receipt = replace(receipt, descriptor_digest="sha256:" + "0" * 64)
    with pytest.raises(InactiveRestoreError), InactiveRestoreSession(receipt):
        pass


@pytest.mark.parametrize("alias", ["hardlink", "symlink"])
def test_database_alias_replacement_cannot_write_original(tmp_path, alias):
    paths, generation, transaction, _, receipt = _prepare(tmp_path)
    source = paths.generation(generation).database
    original = _bytes(tmp_path / "source")
    database = receipt.workspace / "generation" / "finjuice.sqlite3"
    with InactiveRestoreSession(receipt) as session:
        database.unlink()
        if alias == "hardlink":
            os.link(source, database)
        else:
            database.symlink_to(source)
        with pytest.raises(InactiveRestoreError):
            session.execute(_request(generation, "alias", 0), _manual(transaction))
    assert _bytes(tmp_path / "source") == original


def test_root_replacement_invalidates_existing_session(tmp_path):
    _, generation, transaction, backup, receipt = _prepare(tmp_path)
    with InactiveRestoreSession(receipt) as session:
        moved = tmp_path / "original-workspace"
        receipt.workspace.rename(moved)
        restore_workspace(backup, receipt.workspace)
        with pytest.raises(InactiveRestoreError):
            session.execute(_request(generation, "replaced", 0), _manual(transaction))


@pytest.mark.parametrize("failure", ["handler", "receipt"])
def test_failed_handler_rolls_back_manual_edit_and_receipt(tmp_path, monkeypatch, failure):
    _, generation, transaction, _, receipt = _prepare(tmp_path)

    def fail_after_edit(context):
        _manual(transaction)(context)
        raise RuntimeError("synthetic interrupted handler")

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic interrupted receipt")

    handler = fail_after_edit
    if failure == "receipt":
        handler = _manual(transaction)
        monkeypatch.setattr(mutation_module, "_store_receipt", fail_receipt)

    with InactiveRestoreSession(receipt) as session:
        before = session.read_snapshot(lambda reader: reader.rows("transactions"))
        with pytest.raises(RuntimeError, match="interrupted"):
            session.execute(_request(generation, "aborted", 0), handler)
        assert session.read_snapshot(lambda reader: reader.rows("transactions")) == before
        assert session.read_snapshot(lambda reader: reader.info.dataset_revision) == 0
        assert session.read_snapshot(lambda reader: reader.rows("changesets")) == []
        assert session.find_replay(_request(generation, "aborted", 0)) is None


def test_restore_rejects_source_overlap_and_existing_workspace(tmp_path):
    _, _, _, backup, receipt = _prepare(tmp_path)
    original = _bytes(backup)
    with pytest.raises((InactiveRestoreError, RepositoryPathError, FileExistsError)):
        restore_workspace(backup, backup / "nested-workspace")
    with pytest.raises((InactiveRestoreError, RepositoryPathError, FileExistsError)):
        restore_workspace(backup, receipt.workspace)
    assert _bytes(backup) == original


def test_retirement_after_begin_is_rechecked_before_handler(tmp_path, monkeypatch):
    _, generation, transaction, _, receipt = _prepare(tmp_path)
    original_begin = mutation_module._begin_writer_transaction
    with InactiveRestoreSession(receipt) as session, InactiveRestoreSession(receipt) as retiring:

        def begin_then_retire(connection):
            original_begin(connection)
            retiring.retire()

        monkeypatch.setattr(mutation_module, "_begin_writer_transaction", begin_then_retire)
        with pytest.raises(InactiveRestoreError):
            session.execute(_request(generation, "revoked-after-lock", 0), _manual(transaction))
        assert (receipt.workspace / "restore-control" / "retired.json").is_file()

    from finjuice.pipeline.storage.sqlite import RepositoryReader

    with RepositoryReader(receipt.workspace / "generation" / "finjuice.sqlite3") as reader:
        assert reader.info.dataset_revision == 0
        assert reader.rows("changesets") == []


def test_workspace_receipt_binds_the_actual_restored_snapshot(tmp_path, monkeypatch):
    paths, evidence, generation, transactions, _ = _active_repository_with_transactions(
        tmp_path / "source"
    )
    database = paths.generation(generation).database
    backup = tmp_path / "backup"
    first = create_backup(database, backup)
    actual_restore = restore_module.restore_backup
    newer = []

    def advance_pointer_then_restore(*args, **kwargs):
        MutationService(paths, evidence).execute(
            _request(generation, "source-edit", 0),
            lambda context: MutationOutcome(
                result=context.edit_manual_transaction(
                    ManualTransactionEdit(
                        identifier=transactions[0], note_supplied=True, note="later source"
                    )
                )
            ),
        )
        newer.append(create_backup(database, backup))
        return actual_restore(*args, **kwargs)

    monkeypatch.setattr(restore_module, "restore_backup", advance_pointer_then_restore)
    receipt = restore_workspace(backup, tmp_path / "workspace")
    assert receipt.source_manifest_digest == newer[0].manifest_digest != first.manifest_digest
    assert receipt.initial_dataset_revision == 1
    with InactiveRestoreSession(receipt) as session:
        assert (
            session.read_snapshot(lambda reader: reader.rows("transactions"))[0]["notes_manual"]
            == "later source"
        )


def test_descriptor_durability_failure_does_not_return_a_workspace_receipt(tmp_path, monkeypatch):
    _, _, _, backup, _ = _prepare(tmp_path)
    original = _bytes(backup)
    real_sync = descriptor_module.fsync_directory

    def fail_descriptor_parent(path):
        if path.name == "restore-control":
            raise OSError("synthetic descriptor durability failure")
        real_sync(path)

    monkeypatch.setattr(descriptor_module, "fsync_directory", fail_descriptor_parent)
    with pytest.raises(InactiveRestoreError):
        restore_workspace(backup, tmp_path / "failed-workspace")
    assert _bytes(backup) == original
    assert (tmp_path / "failed-workspace").exists()


def test_restore_destination_dangling_symlink_is_not_followed(tmp_path):
    _, _, _, backup, _ = _prepare(tmp_path)
    outside = tmp_path / "outside"
    alias = tmp_path / "workspace-alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(InactiveRestoreError):
        restore_workspace(backup, alias)
    assert not outside.exists()


def test_separate_inactive_handles_serialize_revision_conflicts(tmp_path):
    _, generation, transaction, _, receipt = _prepare(tmp_path)
    start = Barrier(2)

    def apply(session, key):
        with session:
            start.wait(timeout=5)
            try:
                return session.execute(_request(generation, key, 0), _manual(transaction, key))
            except MutationConflictError:
                return None

    first, second = InactiveRestoreSession(receipt), InactiveRestoreSession(receipt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, first, "first"), pool.submit(apply, second, "second")]
        results = [future.result(timeout=10) for future in futures]
    assert sum(result is not None for result in results) == 1
    with InactiveRestoreSession(receipt) as session:
        assert session.read_snapshot(lambda reader: reader.info.dataset_revision) == 1
        assert session.read_snapshot(lambda reader: len(reader.rows("changesets"))) == 1
