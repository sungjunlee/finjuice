"""Status rows/config/import evidence belong to one validated repository revision."""

from __future__ import annotations

from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_status_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import AuthorityEvidenceUnavailableError
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture
from tests.pipeline.test_sqlite_source_lookup import _import_workbook

active_root = _active_root_fixture
query_root = _query_root_fixture


def test_migration_occurrences_are_not_native_imports(query_root: QueryRoot) -> None:
    snapshot = read_status_snapshot(query_root.root, query_root.provider)
    assert snapshot is not None
    assert snapshot.info == snapshot.transactions.info
    assert snapshot.rules is not None
    assert snapshot.rules.config_kind == "rules"
    assert snapshot.rules.parsed_status == "parsed"
    assert snapshot.rules.content == snapshot.transactions.rules_content
    assert snapshot.rules.revision_id
    assert snapshot.rules.updated_at
    assert snapshot.goals is None
    assert snapshot.source_occurrences
    assert {row.origin for row in snapshot.source_occurrences} == {"migration_capture"}
    assert all(row.imported_at is None for row in snapshot.source_occurrences)
    assert any(row.legacy_file_ids == ("source",) for row in snapshot.source_occurrences)


def test_native_completion_evidence_has_uuid_separate_from_file_alias(
    active_root: _ActiveRoot,
) -> None:
    imported = _import_workbook(active_root)
    snapshot = read_status_snapshot(active_root.root, active_root.provider)
    assert snapshot is not None
    source = next(
        row for row in snapshot.source_occurrences if row.occurrence_id == imported["occurrence_id"]
    )
    assert source.origin == "native_import"
    assert source.imported_at is not None
    assert source.legacy_file_ids == ()
    assert source.artifact_id.startswith("sha256:")


def test_status_configs_remain_pinned_and_preserve_independent_parse_flags(
    query_root: QueryRoot,
) -> None:
    facade = StorageMutationFacade(query_root.root, query_root.provider)
    facade.replace_config(ConfigDocument("goals", b"goals: []\n", "opaque", None, "test.v1"))
    paths = AuthorityPaths.for_data_dir(query_root.root).generation(query_root.generation)
    before = {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}
    with RepositoryReader(paths.database) as reader:
        initial = reader.status_snapshot()
        assert initial.goals is not None
        assert initial.goals.parsed_status == "opaque"
        assert initial.goals.content == b"goals: []\n"
        assert before == {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}
        facade.replace_config(ConfigDocument("goals", b"goals: []\n", "invalid", None, "test.v1"))
        pinned = reader.status_snapshot()
        assert pinned == initial
    refreshed = read_status_snapshot(query_root.root, query_root.provider)
    assert refreshed is not None and refreshed.goals is not None
    assert refreshed.goals.parsed_status == "invalid"
    assert refreshed.info.dataset_revision == initial.info.dataset_revision + 1
    with pytest.raises(RuntimeError, match="closed"):
        reader.status_snapshot()


def test_status_legacy_and_missing_evidence_are_distinct(
    query_root: QueryRoot, tmp_path: Path
) -> None:
    assert read_status_snapshot(tmp_path / "unactivated") is None
    with pytest.raises(AuthorityEvidenceUnavailableError):
        read_status_snapshot(query_root.root)


def test_unproven_occurrences_keep_other_origin_and_all_file_aliases(tmp_path: Path) -> None:
    from tests.pipeline.test_sqlite_transaction_reads import _seed

    paths = _seed(tmp_path)
    with RepositoryReader(paths.database) as reader:
        snapshot = reader.status_snapshot()
    assert len(snapshot.source_occurrences) == 1
    occurrence = snapshot.source_occurrences[0]
    assert occurrence.origin == "other"
    assert occurrence.legacy_file_ids == ("first", "second")


def test_goal_object_corruption_is_rejected_without_echoing_bytes(query_root: QueryRoot) -> None:
    import hashlib

    from finjuice.pipeline.storage.sqlite.errors import ObjectCorruptionError

    content = b"goals: []\n"
    facade = StorageMutationFacade(query_root.root, query_root.provider)
    facade.replace_config(ConfigDocument("goals", content, "opaque", None, "test.v1"))
    paths = AuthorityPaths.for_data_dir(query_root.root).generation(query_root.generation)
    with RepositoryReader(paths.database) as reader:
        goal_object = paths.object_path(hashlib.sha256(content).hexdigest())
        goal_object.chmod(0o600)
        goal_object.write_bytes(b"private-sentinel")
        with pytest.raises(ObjectCorruptionError) as error:
            reader.status_snapshot()
        assert "private-sentinel" not in str(error.value)


def test_legacy_history_uses_only_proven_primary_rows_and_preserves_timestamps(
    tmp_path: Path,
) -> None:
    from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
    from finjuice.pipeline.migration import build_migration, plan_migration

    source = tmp_path / "source"
    history = source / "metadata/import_history.csv"
    history.parent.mkdir(parents=True)
    history.write_text(
        "file_id,imported_at\nlegacy-id,2024-01-02 03:04:05\n"
        "legacy-id,2024-02-03T04:05:06+09:00\nambiguous,2024-03-01,extra\n"
    )
    other = source / "other/metadata/import_history.csv"
    other.parent.mkdir(parents=True)
    other.write_text("file_id,imported_at\nwrong-path,2099-01-01\n")
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        snapshot = reader.status_snapshot()
    assert [
        (row.legacy_file_id, row.imported_at, row.source_row)
        for row in snapshot.legacy_import_history
    ] == [
        ("legacy-id", "2024-01-02 03:04:05", 1),
        ("legacy-id", "2024-02-03T04:05:06+09:00", 2),
    ]
    assert len({row.provenance_id for row in snapshot.legacy_import_history}) == 2
    assert all(row.origin == "migration_capture" for row in snapshot.source_occurrences)
