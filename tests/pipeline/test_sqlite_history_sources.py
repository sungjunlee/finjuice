"""History file inventory is proved independently by captured manifests."""

import sqlite3
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.history_sources import verified_history_sources
from tests.cli.commands.test_repository_assets import _activate


def _build(tmp_path: Path, content: bytes | None):
    source = tmp_path / "source"
    source.mkdir()
    if content is not None:
        metadata = source / "metadata"
        metadata.mkdir()
        (metadata / "import_history.csv").write_bytes(content)
    (source / "marker.txt").write_bytes(b"synthetic")
    root = _activate(source, tmp_path)
    return AuthorityPaths.for_data_dir(root.root).generation(root.generation)


@pytest.mark.parametrize(
    "content", [None, b"file_id,imported_at\r\n", b"file_id,imported_at\nf,invalid-date\n"]
)
def test_original_bytes_and_absence(tmp_path: Path, content: bytes | None) -> None:
    paths = _build(tmp_path, content)
    with sqlite3.connect(paths.database) as connection:
        result = verified_history_sources(connection, paths)
        assert len(result) == (0 if content is None else 1)
        if result:
            assert result[0].content == content
            assert result[0].locator == {
                "root": "data",
                "path": "metadata/import_history.csv",
                "row": None,
            }


@pytest.mark.parametrize(
    "damage", ["occurrence", "payload", "payload_id", "locator", "identity", "anchor"]
)
def test_missing_or_changed_evidence_never_becomes_absence(tmp_path: Path, damage: str) -> None:
    paths = _build(tmp_path, b"file_id,imported_at\nf,date\n")
    with sqlite3.connect(paths.database) as connection:
        source = verified_history_sources(connection, paths)[0]
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall():
            connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        if damage == "occurrence":
            connection.execute(
                "DELETE FROM source_occurrences WHERE entity_id=?", (source.occurrence_id,)
            )
        elif damage == "identity":
            connection.execute(
                "DELETE FROM migration_identities WHERE entity_id=?", (source.occurrence_id,)
            )
        elif damage == "anchor":
            connection.execute(
                "DELETE FROM source_occurrences WHERE occurrence_kind='legacy_capture_manifest'"
            )
        elif damage == "payload_id":
            connection.execute(
                "UPDATE legacy_payloads SET payload_id=? WHERE provenance_id IN "
                "(SELECT provenance_id FROM record_provenance WHERE source_occurrence_id=? "
                "AND json_extract(source_coordinate_json, '$.row') IS NULL)",
                ("11111111-1111-4111-8111-111111111111", source.occurrence_id),
            )
        elif damage == "payload":
            connection.execute(
                "UPDATE legacy_payloads SET payload_json='{}' WHERE provenance_id IN "
                "(SELECT provenance_id FROM record_provenance WHERE source_occurrence_id=?)",
                (source.occurrence_id,),
            )
        else:
            connection.execute(
                "UPDATE record_provenance SET source_coordinate_json='{}' "
                "WHERE source_occurrence_id=?",
                (source.occurrence_id,),
            )
        with pytest.raises(RepositoryIntegrityError, match="^Canonical history source evidence"):
            verified_history_sources(connection, paths)


def test_object_corruption_fails_statically(tmp_path: Path) -> None:
    paths = _build(tmp_path, b"file_id,imported_at\nf,date\n")
    with sqlite3.connect(paths.database) as connection:
        source = verified_history_sources(connection, paths)[0]
        object_path = paths.object_path(source.artifact_id.removeprefix("sha256:"))
        object_path.chmod(0o600)
        object_path.write_bytes(b"PRIVATE_CORRUPTION")
        with pytest.raises(RepositoryIntegrityError) as error:
            verified_history_sources(connection, paths)
        assert "PRIVATE_CORRUPTION" not in str(error.value)


def test_native_only_empty_allowed(tmp_path: Path) -> None:
    from uuid import uuid4

    from finjuice.pipeline.storage.sqlite import RepositoryBuilder
    from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

    paths = GenerationPaths(tmp_path / "native")
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        builder.finalize()
    with sqlite3.connect(paths.database) as connection:
        assert verified_history_sources(connection, paths) == ()


def test_auxiliary_history_is_proved_and_excluded(tmp_path: Path) -> None:
    from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
    from finjuice.pipeline.backup.types import SourceRoot
    from finjuice.pipeline.migration import build_migration, plan_migration
    from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

    source, aux = tmp_path / "source", tmp_path / "aux"
    for directory, content in ((source, b"primary"), (aux, b"auxiliary")):
        (directory / "metadata").mkdir(parents=True)
        (directory / "metadata/import_history.csv").write_bytes(content)
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("test",)),
            extra_roots=(SourceRoot("aux", "required", aux),),
        )
    )
    plan = tmp_path / "plan.json"
    plan_migration(capture, output=plan, active_data_dir=source)
    paths = GenerationPaths(tmp_path / "candidate")
    build_migration(plan, paths.root, active_data_dir=source)
    with sqlite3.connect(paths.database) as connection:
        result = verified_history_sources(connection, paths)
    assert len(result) == 1 and result[0].content == b"primary"
