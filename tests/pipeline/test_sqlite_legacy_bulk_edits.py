"""Bulk edits retain source-backed legacy arrays across all mutation boundaries."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.bulk_tagging import BulkTagCommand
from finjuice.pipeline.storage.sqlite.bulk_transfer import BulkTransferCommand
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from tests.pipeline.test_sqlite_bulk_mutations import _evidence, _facade, _write_activation


def _migrate(tmp_path: Path):
    source = tmp_path / "source"
    partition = source / "transactions/2026/09/transactions.csv"
    partition.parent.mkdir(parents=True)
    rows = [
        dict(
            row_hash=str(index),
            date="2026-09-01",
            time="12:00:00",
            datetime="2026-09-01T12:00:00",
            type_norm="transfer",
            account=f"account-{index}",
            amount=amount,
            currency="KRW",
            category_final="persisted",
            tags_rule='[" old ", "", " old "]',
            tags_ai='[" ai ", "", " ai "]',
            tags_manual='[" x ", "", " x "]',
            tags_final='[" persisted ", "", " persisted "]',
            notes_manual="manual\nnotes",
            is_transfer="1",
            transfer_group_id="legacy-pair",
            is_transfer_candidate="1",
        )
        for index, amount in enumerate(("-123.4500", "123.4500"))
    ]
    with partition.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (source / "rules.yaml").write_text("rules: []\n")
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    active = paths.generation(generation)
    shutil.copytree(candidate, active.root)
    _write_activation(paths, generation)
    return _facade(paths, _evidence(), root), active.database, generation, source


def _state(database: Path):
    with RepositoryReader(database) as reader:
        return reader.info.dataset_revision, sorted(
            reader.rows("transactions"), key=lambda r: r["entity_id"]
        )


@pytest.mark.parametrize("operation", ["tag", "transfer"])
def test_migrated_bulk_preview_apply_replay_noop_preserves_unrelated_fields(
    tmp_path: Path, operation: str
) -> None:
    facade, database, generation, source = _migrate(tmp_path)
    source_before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    method = facade.recompute_tags if operation == "tag" else facade.recompute_transfers
    command = BulkTagCommand() if operation == "tag" else BulkTransferCommand()
    before = _state(database)
    preview = method(command, dry_run=True)
    assert preview.result["updated"] == 2
    assert _state(database) == before
    identity = MutationIdentity("apply", generation, 0)
    receipt = method(command, identity=identity)
    assert receipt.state_changed and receipt.committed_revision == 1
    assert receipt.result == preview.result
    after = _state(database)
    with RepositoryReader(database) as reader:
        entries = [
            row for row in reader.rows("changeset_entries") if row["entity_kind"] == "transaction"
        ]
    assert len(entries) == 2
    for entry in entries:
        audited_before = json.loads(entry["before_json"])
        if operation == "tag":
            assert audited_before["tags_final"] == [" persisted ", "", " persisted "]
            assert audited_before["tags_rule"] == [" old ", "", " old "]
        else:
            assert set(audited_before) == {"is_transfer", "transfer_group_id"}
    for old, new in zip(before[1], after[1], strict=True):
        if operation == "transfer":
            changed = {"is_transfer", "transfer_group_id"}
            assert new["is_transfer"] == 0 and new["transfer_group_id"] is None
        else:
            changed = {
                "tags_rule_json",
                "tags_final_json",
                "category_final",
                "confidence_value_id",
                "needs_review",
            }
            assert json.loads(new["tags_final_json"]) == ["ai", "x"]
            assert new["tags_rule_json"] == "[]"
        assert {k: v for k, v in old.items() if k not in changed} == {
            k: v for k, v in new.items() if k not in changed
        }
    replay = method(command, identity=identity)
    assert replay.replayed and replay.result == receipt.result
    assert _state(database) == after
    noop_preview = method(command, dry_run=True)
    assert noop_preview.result["updated"] == 0
    noop = method(command, identity=MutationIdentity("noop", generation, 1))
    assert not noop.state_changed and noop.committed_revision == 1
    assert noop.result == noop_preview.result
    assert _state(database) == after
    assert source_before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("operation", ["tag", "transfer"])
def test_native_bulk_arrays_still_require_canonical_state(tmp_path: Path, operation: str) -> None:
    from tests.pipeline.test_sqlite_transaction_reads import _seed

    native = _seed(tmp_path)
    with RepositoryReader(native.database) as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    active = paths.generation(generation)
    shutil.copytree(native.root, active.root)
    _write_activation(paths, generation)
    facade = _facade(paths, _evidence(), root)
    if operation == "tag":
        from finjuice.pipeline.storage.mutation_facade import ConfigDocument

        facade.replace_config(
            ConfigDocument("rules", b"rules: []\n", "parsed", {"rules": []}, "test.v1")
        )
    method = facade.recompute_tags if operation == "tag" else facade.recompute_transfers
    command = BulkTagCommand() if operation == "tag" else BulkTransferCommand()
    before = _state(active.database)
    with pytest.raises(RepositoryIntegrityError, match="canonical"):
        method(command, dry_run=True)
    with pytest.raises(RepositoryIntegrityError, match="canonical"):
        method(command)
    assert _state(active.database) == before


def test_legacy_before_is_evidence_but_proposed_tags_remain_validated() -> None:
    from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
    from finjuice.pipeline.storage.sqlite.mutations import (
        _derived_update_parts,
        _reject_stale_derived_before,
    )

    stored = {"tags_final": [" old ", "", " old "]}
    after = {"tags_final": ["new"]}
    _reject_stale_derived_before(stored, stored, after)
    with pytest.raises(MutationValidationError, match="does not match"):
        _reject_stale_derived_before({"tags_final": ["old"]}, stored, after)
    with pytest.raises(MutationValidationError, match="canonical"):
        _derived_update_parts({"tags_final": [""]}, stored)
