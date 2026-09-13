"""Strict history retains every source record or fails without a partial success."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import AuthorityPaths
from finjuice.pipeline.storage.read_facade import read_history_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.history_reads import history_snapshot
from tests.cli.commands.test_repository_assets import _activate
from tests.pipeline.test_sqlite_exact_import import _import, _Repo, _tx_book, _tx_row
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture

repo = _repo_fixture
CONTENT = (
    b"file_id,imported_at,original_filename,source_rows,archived\r\n"
    b'same,not-a-date,"line1\nline2.xlsx",004,true\r\n'
    b'same,,"",bad,unknown\r\n'
)


def _active(tmp_path: Path, content: bytes = CONTENT):
    source = tmp_path / "source"
    path = source / "metadata/import_history.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    opaque = source / "transactions/2026/01/transactions.csv"
    opaque.parent.mkdir(parents=True)
    opaque.write_bytes(b"amount,amount\n1,2\n")
    return _activate(source, tmp_path)


def test_legacy_records_preserve_null_lexical_duplicates_and_detach(tmp_path: Path) -> None:
    root = _active(tmp_path)
    snapshot = read_history_snapshot(root.root, root.provider)
    assert snapshot is not None
    first, second = snapshot.legacy_records
    assert first.source_row == 1 and second.source_row == 2
    assert first.fields["file_id"] == second.fields["file_id"] == "same"
    assert first.fields["source_rows"] == "004"
    assert first.fields["original_filename"] == "line1\nline2.xlsx"
    assert second.fields["imported_at"] is None and second.fields["original_filename"] == ""
    assert second.fields["source_rows"] == "bad" and second.fields["archived"] == "unknown"
    first.raw_payload["cells"][0]["value"] = "changed"
    fresh = read_history_snapshot(root.root, root.provider)
    assert fresh is not None and fresh.legacy_records[0].raw_payload["cells"][0]["value"] == "same"


@pytest.mark.parametrize(
    "content",
    [
        b"file_id,imported_at\nx,time,extra\n",
        b"file_id,file_id\nx,y\n",
        b"file_id\n",
        b'file_id,imported_at\nx,"unfinished',
        b"\xff",
    ],
)
def test_malformed_legacy_history_never_returns_partial_or_empty(
    tmp_path: Path, content: bytes
) -> None:
    root = _active(tmp_path, content)
    with pytest.raises(RepositoryIntegrityError, match="Canonical history evidence"):
        read_history_snapshot(root.root, root.provider)


def test_verified_header_only_is_empty(tmp_path: Path) -> None:
    root = _active(tmp_path, b"file_id,imported_at\n")
    snapshot = read_history_snapshot(root.root, root.provider)
    assert snapshot is not None and snapshot.legacy_records == ()


@pytest.mark.parametrize("damage", ["missing", "extra", "payload"])
def test_strict_row_layer_detects_ordinal_and_payload_damage(tmp_path: Path, damage: str) -> None:
    root = _active(tmp_path)
    # Modify only the reader's detached inspection copy to exercise row coverage
    # independently of the outer repository inspection's corruption checks.
    with RepositoryReader(
        AuthorityPaths.for_data_dir(root.root).generation(root.generation).database
    ) as reader:
        connection = sqlite3.connect(":memory:")
        reader._connection.backup(connection)
        rows = connection.execute(
            "SELECT prov.provenance_id, prov.source_coordinate_json FROM record_provenance AS prov "
            "WHERE json_extract(prov.source_coordinate_json, '$.path') "
            "= 'metadata/import_history.csv' "
            "AND json_extract(prov.source_coordinate_json, '$.row') = 1"
        ).fetchall()
        provenance, coordinate = rows[0]
        connection.execute("PRAGMA query_only = OFF")
        connection.execute("DROP TRIGGER IF EXISTS legacy_payloads_no_update")
        connection.execute("DROP TRIGGER IF EXISTS legacy_payloads_no_delete")
        connection.execute("DROP TRIGGER IF EXISTS record_provenance_no_update")
        if damage == "missing":
            connection.execute("DELETE FROM legacy_payloads WHERE provenance_id = ?", (provenance,))
        elif damage == "extra":
            locator = json.loads(coordinate)
            locator["row"] = 99
            connection.execute(
                "UPDATE record_provenance SET source_coordinate_json = ?, legacy_locator_json = ? "
                "WHERE provenance_id = ?",
                (json.dumps(locator), json.dumps(locator), provenance),
            )
        else:
            connection.execute(
                "UPDATE legacy_payloads SET payload_json = '{}' WHERE provenance_id = ?",
                (provenance,),
            )
        with pytest.raises(RepositoryIntegrityError):
            history_snapshot(connection, reader._repository_paths, reader.info)
        connection.close()


def test_native_complete_noop_pin_and_closed_reader(repo: _Repo) -> None:
    data = _tx_book(_tx_row(2))
    with RepositoryReader(repo.database) as reader:
        before = reader.history_snapshot()
        _import(repo, data, key="first", revision=0)
        assert reader.history_snapshot() == before
    with pytest.raises(RuntimeError, match="closed"):
        reader.history_snapshot()
    with RepositoryReader(repo.database) as fresh:
        snapshot = fresh.history_snapshot()
        record = snapshot.native_records[0]
        assert record.counts["transactions"]["inserted"] == 1
        assert record.legacy_file_ids == ()
        record.counts["transactions"]["inserted"] = 999
        assert fresh.history_snapshot().native_records[0].counts["transactions"]["inserted"] == 1
    _import(repo, data, key="noop", revision=1)
    with RepositoryReader(repo.database) as fresh:
        assert len(fresh.history_snapshot().native_records) == 1


def test_native_malformed_completion_is_not_hidden(repo: _Repo) -> None:
    _import(repo, _tx_book(_tx_row(2)), key="first", revision=0)
    with RepositoryReader(repo.database) as reader, sqlite3.connect(":memory:") as connection:
        reader._connection.backup(connection)
        connection.execute("DROP TRIGGER IF EXISTS legacy_payloads_no_update")
        connection.execute(
            "UPDATE legacy_payloads SET payload_json = '{}' WHERE provenance_id IN "
            "(SELECT provenance_id FROM record_provenance "
            "WHERE json_extract(source_coordinate_json, '$.kind') = 'exact_xlsx_import_manifest')"
        )
        with pytest.raises(RepositoryIntegrityError, match="Canonical history evidence"):
            history_snapshot(connection, reader._repository_paths, reader.info)


@pytest.mark.parametrize("malformed", [False, True])
def test_native_direct_alias_requires_matching_provenance(repo: _Repo, malformed: bool) -> None:
    from finjuice.pipeline.storage.sqlite.ids import new_entity_id

    _import(repo, _tx_book(_tx_row(2)), key="first", revision=0)
    _import(repo, _tx_book(_tx_row(3)), key="second", revision=1)
    with RepositoryReader(repo.database) as reader, sqlite3.connect(":memory:") as connection:
        reader._connection.backup(connection)
        initial = reader.history_snapshot()
        first, second = initial.native_records
        connection.execute(
            "INSERT INTO legacy_identifiers (mapping_id,entity_id,identifier_kind,identifier_value,"
            "provenance_id,capture_manifest_digest) VALUES (?,?,'file_id',?,?,?)",
            (
                new_entity_id(),
                first.occurrence_id,
                "explicit-alias",
                second.provenance_id if malformed else first.provenance_id,
                "a" * 64,
            ),
        )
        if malformed:
            with pytest.raises(RepositoryIntegrityError):
                history_snapshot(connection, reader._repository_paths, reader.info)
        else:
            snapshot = history_snapshot(connection, reader._repository_paths, reader.info)
            assert snapshot.native_records[0].legacy_file_ids == ("explicit-alias",)
            assert snapshot.native_records[1].legacy_file_ids == ()


@pytest.mark.parametrize("kind", ["provenance", "payload", "observation"])
def test_history_row_deterministic_ids_cannot_be_replaced(tmp_path: Path, kind: str) -> None:
    from finjuice.pipeline.storage.sqlite.history_rows import legacy_history_records
    from finjuice.pipeline.storage.sqlite.history_sources import verified_history_sources
    from finjuice.pipeline.storage.sqlite.ids import migration_entity_id

    root = _active(tmp_path)
    database = AuthorityPaths.for_data_dir(root.root).generation(root.generation).database
    with RepositoryReader(database) as reader, sqlite3.connect(":memory:") as connection:
        reader._connection.backup(connection)
        source = verified_history_sources(connection, reader._repository_paths)[0]
        provenance = connection.execute(
            "SELECT provenance_id FROM record_provenance WHERE source_occurrence_id = ? "
            "AND json_extract(source_coordinate_json, '$.row') = 1",
            (source.occurrence_id,),
        ).fetchone()[0]
        changed = migration_entity_id("a" * 64, "observation", {"wrong": True})
        if kind == "payload":
            connection.execute("DROP TRIGGER legacy_payloads_no_update")
            connection.execute(
                "UPDATE legacy_payloads SET payload_id = ? WHERE provenance_id = ?",
                (changed, provenance),
            )
        elif kind == "provenance":
            connection.execute("DROP TRIGGER record_provenance_no_update")
            connection.execute("DROP TRIGGER legacy_payloads_no_update")
            connection.execute(
                "UPDATE record_provenance SET provenance_id = ? WHERE provenance_id = ?",
                (changed, provenance),
            )
            connection.execute(
                "UPDATE legacy_payloads SET provenance_id = ? WHERE provenance_id = ?",
                (changed, provenance),
            )
        else:
            original = connection.execute(
                "SELECT observation.entity_id FROM observations AS observation "
                "JOIN migration_identities AS identity "
                "ON identity.entity_id = observation.entity_id "
                "WHERE observation.source_occurrence_id = ? "
                "AND json_extract(identity.canonical_locator_json, '$.row') = 1",
                (source.occurrence_id,),
            ).fetchone()[0]
            connection.execute("DROP TRIGGER IF EXISTS observations_no_update")
            connection.execute("DROP TRIGGER IF EXISTS migration_identities_no_update")
            connection.execute(
                "UPDATE observations SET entity_id = ? WHERE entity_id = ?", (changed, original)
            )
            connection.execute(
                "UPDATE migration_identities SET entity_id = ? WHERE entity_id = ?",
                (changed, original),
            )
        with pytest.raises(ValueError, match="identity"):
            legacy_history_records(connection, source)


@pytest.mark.parametrize("damage", ["kind", "coordinate", "payload", "orphan", "extra"])
def test_native_manifest_inventory_cannot_disappear(repo: _Repo, damage: str) -> None:
    from finjuice.pipeline.storage.sqlite.exact_import.constants import (
        MANIFEST_COORDINATE_KIND,
        MANIFEST_KIND,
    )

    _import(repo, _tx_book(_tx_row(2)), key="first", revision=0)
    with RepositoryReader(repo.database) as reader, sqlite3.connect(":memory:") as connection:
        reader._connection.backup(connection)
        record = reader.history_snapshot().native_records[0]
        connection.execute("DROP TRIGGER IF EXISTS source_occurrences_no_update")
        connection.execute("DROP TRIGGER IF EXISTS record_provenance_no_update")
        connection.execute("DROP TRIGGER IF EXISTS record_provenance_no_delete")
        connection.execute("DROP TRIGGER IF EXISTS legacy_payloads_no_update")
        if damage == "kind":
            connection.execute(
                "UPDATE source_occurrences SET occurrence_kind = 'synthetic_other' "
                "WHERE entity_id = ?",
                (record.occurrence_id,),
            )
        elif damage == "coordinate":
            connection.execute(
                "UPDATE record_provenance SET source_coordinate_json = '{}' "
                "WHERE provenance_id = ?",
                (record.provenance_id,),
            )
        elif damage == "payload":
            connection.execute(
                "UPDATE legacy_payloads SET payload_json = '{}' WHERE provenance_id = ?",
                (record.provenance_id,),
            )
        elif damage == "orphan":
            connection.execute(
                "DELETE FROM record_provenance WHERE provenance_id = ?",
                (record.provenance_id,),
            )
        else:
            other = connection.execute(
                "SELECT prov.provenance_id FROM record_provenance AS prov "
                "JOIN legacy_payloads AS payload ON payload.provenance_id = prov.provenance_id "
                "WHERE prov.provenance_id != ? LIMIT 1",
                (record.provenance_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE record_provenance SET source_coordinate_json = ? WHERE provenance_id = ?",
                (json.dumps({"kind": MANIFEST_COORDINATE_KIND, "role": "root"}), other),
            )
            connection.execute(
                "UPDATE legacy_payloads SET payload_json = ? WHERE provenance_id = ?",
                (json.dumps({"manifest_kind": MANIFEST_KIND, "status": "completed"}), other),
            )
        with pytest.raises(RepositoryIntegrityError, match="Canonical history evidence"):
            history_snapshot(connection, reader._repository_paths, reader.info)
