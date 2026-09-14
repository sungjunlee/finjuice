"""Snapshots retain selected config history and its exact immutable object closure."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite import backup as backup_module
from finjuice.pipeline.storage.sqlite.backup import (
    DATABASE_BASENAME,
    backup_status,
    create_backup,
    read_backup_manifest,
    restore_backup,
)
from finjuice.pipeline.storage.sqlite.errors import RepositoryBackupError
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source

RULE_A = b"# selected A exact bytes\nversion: 1\nrules: []\n"
RULE_B = b"# selected B exact bytes\nversion: 1\nrules: []\n"
RULE_C = b"# selected C after snapshot\nversion: 1\nrules: []\n"


def _database(root):
    return AuthorityPaths.for_data_dir(root.root).generation(root.generation).database


def _replace_rules(root, content):
    return StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument.from_validated_yaml("rules", content, parser_version="test.rules.v1")
    )


def _closure(database: Path):
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        tables = {
            "config_heads": connection.execute(
                "SELECT * FROM config_heads ORDER BY config_kind"
            ).fetchall(),
            "config_revisions": connection.execute(
                "SELECT * FROM config_revisions ORDER BY entity_id"
            ).fetchall(),
            "source_artifacts": connection.execute(
                "SELECT * FROM source_artifacts ORDER BY source_artifact_id"
            ).fetchall(),
        }
        paths = connection.execute(
            "SELECT object_path FROM source_artifacts ORDER BY object_path"
        ).fetchall()
    objects = {path: (database.parent / path).read_bytes() for (path,) in paths}
    return tables, objects


def _assert_closure(root: Path, expected):
    assert _closure(root / DATABASE_BASENAME) == expected
    manifest = read_backup_manifest(root)
    assert {entry.path for entry in manifest.files if entry.role == "object"} == set(expected[1])


def test_config_history_and_objects_are_pinned_before_live_head_mutation(tmp_path, monkeypatch):
    source = _source(tmp_path)
    (source / "rules.yaml").write_bytes(RULE_A)
    root = _activate(source, tmp_path)
    _replace_rules(root, RULE_B)
    database = _database(root)
    expected = _closure(database)
    assert RULE_A in expected[1].values() and RULE_B in expected[1].values()
    original = backup_module._snapshot_into
    calls = []

    def capture_then_mutate(*args, **kwargs):
        info = original(*args, **kwargs)
        calls.append(info.dataset_revision)
        _replace_rules(root, RULE_C)
        (root.root / "rules.yaml").write_bytes(b"PRIVATE_LIVE_YAML: [")
        return info

    with monkeypatch.context() as patch:
        patch.setattr(backup_module, "_snapshot_into", capture_then_mutate)
        created = create_backup(database, tmp_path / "backup")
    assert calls == [created.dataset_revision]
    assert RULE_C in _closure(database)[1].values()
    _assert_closure(created.manifest_path.parent, expected)
    restored = tmp_path / "restored"
    assert restore_backup(tmp_path / "backup", restored).verified
    _assert_closure(restored, expected)
    with RepositoryReader(restored / DATABASE_BASENAME) as reader:
        assert reader.status_snapshot().rules.content == RULE_B
    repeated = create_backup(restored / DATABASE_BASENAME, tmp_path / "rebackup")
    _assert_closure(repeated.manifest_path.parent, expected)
    final = tmp_path / "final"
    assert restore_backup(tmp_path / "rebackup", final).verified
    _assert_closure(final, expected)


@pytest.mark.parametrize("state", ["invalid", "unselected"])
def test_invalid_and_unselected_config_evidence_survives_backup(tmp_path, state):
    source = _source(tmp_path)
    content = (
        b"PRIVATE_INVALID_GOALS: [" if state == "invalid" else (source / "goals.yaml").read_bytes()
    )
    path = source / "goals.yaml"
    path.unlink()
    if state == "unselected":
        path = source / "nested" / "goals.yaml"
        path.parent.mkdir()
    path.write_bytes(content)
    root = _activate(source, tmp_path)
    database = _database(root)
    expected = _closure(database)
    with RepositoryReader(database) as reader:
        selection = reader.portfolio_snapshot().goals
    assert selection.selection_state == ("selected" if state == "invalid" else "unselected")
    if state == "invalid":
        assert selection.head.parsed_status == "invalid"
    else:
        assert selection.head is None and selection.revisions
    assert content in expected[1].values()
    created = create_backup(database, tmp_path / "backup")
    _assert_closure(created.manifest_path.parent, expected)
    restored = tmp_path / "restored"
    assert restore_backup(tmp_path / "backup", restored).verified
    _assert_closure(restored, expected)
    with RepositoryReader(restored / DATABASE_BASENAME) as reader:
        assert reader.portfolio_snapshot().goals == selection


def test_copied_config_object_tamper_rejects_status_and_restore(tmp_path):
    source = _source(tmp_path)
    (source / "rules.yaml").write_bytes(RULE_A)
    root = _activate(source, tmp_path)
    _replace_rules(root, RULE_B)
    expected = _closure(_database(root))
    config_path = next(path for path, content in expected[1].items() if content == RULE_A)
    created = create_backup(_database(root), tmp_path / "backup")
    copied = created.manifest_path.parent / config_path
    copied.chmod(0o600)
    copied.write_bytes(b"X" + RULE_A[1:])
    assert not backup_status(tmp_path / "backup").complete
    with pytest.raises(RepositoryBackupError):
        restore_backup(tmp_path / "backup", tmp_path / "restore")
    assert _closure(_database(root)) == expected
