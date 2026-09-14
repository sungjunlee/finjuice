"""Manual edits preserve migration-era tag sequences until classification changes."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.mutations import (
    ManualTransactionEdit,
    _parse_preserved_string_array,
    _parse_string_array,
)
from tests.migration.test_manual_policy import _capture
from tests.pipeline.test_sqlite_bulk_mutations import _evidence, _facade, _write_activation


def test_real_migration_note_edit_noop_replay_and_classification_boundary(tmp_path: Path) -> None:
    source, capture, _originals = _capture(tmp_path)
    source_before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    plan, candidate = tmp_path / "plan.json", tmp_path / "candidate"
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    active = paths.generation(generation)
    shutil.copytree(candidate, active.root)
    _write_activation(paths, generation)
    facade = _facade(paths, _evidence(), root)
    with RepositoryReader(active.database) as reader:
        original = next(
            row
            for row in reader.rows("transactions")
            if json.loads(row["tags_manual_json"]) == [" x ", "x", " x ", "", "  "]
        )
    transaction = original["entity_id"]
    edit = ManualTransactionEdit(identifier=transaction, note_supplied=True, note="edited")
    identity = MutationIdentity("note", generation, 0)
    receipt = facade.edit_manual_transaction(edit, identity=identity)
    assert receipt.state_changed and receipt.committed_revision == 1
    assert receipt.result["tags_manual"] == [" x ", "x", " x ", "", "  "]
    assert receipt.result["tags_final"] == ["persisted", "persisted"]
    assert receipt.result["category_final"] == "persisted-category"
    with RepositoryReader(active.database) as reader:
        current = next(
            row for row in reader.rows("transactions") if row["entity_id"] == transaction
        )
    assert current == {**original, "notes_manual": "edited"}
    replay = facade.edit_manual_transaction(edit, identity=identity)
    assert replay.replayed and replay.result == receipt.result
    assert replay.committed_revision == 1
    noop = facade.edit_manual_transaction(edit, identity=MutationIdentity("noop", generation, 1))
    assert not noop.state_changed and noop.committed_revision == 1
    assert noop.result["tags_manual"] == receipt.result["tags_manual"]
    classification = facade.edit_manual_transaction(
        ManualTransactionEdit(identifier=transaction, add_tags=("new",)),
        identity=MutationIdentity("classification", generation, 1),
    )
    assert classification.committed_revision == 2
    assert classification.result["tags_manual"] == ["x", "new"]
    assert classification.result["tags_final"] == ["x", "new"]
    assert classification.result["category_final"] == "A"
    assert source_before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("value", ['["same","same"]', '[""]'])
def test_native_parser_still_rejects_noncanonical_sequences(value: str) -> None:
    with pytest.raises(RepositoryIntegrityError, match="canonical"):
        _parse_string_array(value)
    assert _parse_preserved_string_array(value) == json.loads(value)


@pytest.mark.parametrize("value", ["[1]", '{"x": 1}', "[NaN]", "invalid"])
def test_preserved_parser_still_rejects_invalid_tag_types(value: str) -> None:
    with pytest.raises(RepositoryIntegrityError):
        _parse_preserved_string_array(value)


def test_native_manual_edit_does_not_gain_legacy_parser_exemption(tmp_path: Path) -> None:
    from tests.pipeline.test_sqlite_transaction_reads import _seed

    native = _seed(tmp_path)
    with RepositoryReader(native.database) as reader:
        generation = reader.info.dataset_generation
        transaction = reader.rows("transactions")[0]["entity_id"]
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    active = paths.generation(generation)
    shutil.copytree(native.root, active.root)
    _write_activation(paths, generation)
    facade = _facade(paths, _evidence(), root)
    with pytest.raises(RepositoryIntegrityError, match="canonical"):
        facade.edit_manual_transaction(
            ManualTransactionEdit(identifier=transaction, note_supplied=True, note="edited")
        )
    with RepositoryReader(active.database) as reader:
        assert reader.info.dataset_revision == 0
        assert all(row["notes_manual"] == "line1\nline2" for row in reader.rows("transactions"))


@pytest.mark.parametrize(
    "column", ["tags_manual_json", "tags_final_json", "tags_rule_json", "tags_ai_json"]
)
def test_current_schema_rejects_null_tag_arrays(tmp_path: Path, column: str) -> None:
    from tests.pipeline.test_sqlite_transaction_reads import _seed

    native = _seed(tmp_path)
    with sqlite3.connect(native.database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            connection.execute(f"UPDATE transactions SET {column} = NULL")
