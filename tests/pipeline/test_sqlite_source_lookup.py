"""Synthetic tests for the read-only archived source resolver."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import ExactImportCommand
from finjuice.pipeline.storage.sqlite.exact_import import capture_exact_xlsx
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.source_lookup import (
    SourceLookupError,
    resolve_archived_source,
)
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

active_root = _active_root_fixture


def _generation_paths(active: _ActiveRoot):
    authority = active.facade.dispatch().authority
    assert isinstance(authority, RepositoryAuthority)
    return authority.paths


def _import_workbook(active: _ActiveRoot, extra: str | None = None) -> dict[str, str]:
    extra_sheets = None
    if extra is not None:
        from tests.pipeline.test_sqlite_exact_import import _inline, _row

        extra_sheets = {"notes": _row(1, _inline("A1", extra))}
    data = _tx_book(_tx_row(2), extra_sheets=extra_sheets)
    receipt = active.facade.import_exact_xlsx(ExactImportCommand(capture_exact_xlsx(data)))
    result = dict(receipt.result)
    return {
        "artifact_id": str(result["artifact_id"]),
        "digest_hex": str(result["artifact_id"]).removeprefix("sha256:"),
        "occurrence_id": str(result["occurrence_id"]),
    }


def _provenance_id(database: Path, occurrence_id: str) -> str:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT provenance_id FROM record_provenance "
            "WHERE source_occurrence_id = ? ORDER BY provenance_id",
            (occurrence_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def _insert_file_id(
    database: Path,
    *,
    occurrence_id: str,
    file_id: str,
    provenance_id: str | None,
    digest_hex: str,
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO legacy_identifiers "
            "(mapping_id, entity_id, identifier_kind, identifier_value, "
            "provenance_id, capture_manifest_digest) VALUES (?, ?, 'file_id', ?, ?, ?)",
            (new_entity_id(), occurrence_id, file_id, provenance_id, digest_hex),
        )
        connection.commit()
    finally:
        connection.close()


def test_resolves_occurrence_and_artifact_to_the_same_capture(active_root: _ActiveRoot) -> None:
    imported = _import_workbook(active_root)
    paths = _generation_paths(active_root)

    by_occurrence = resolve_archived_source(paths, imported["occurrence_id"])
    by_artifact = resolve_archived_source(paths, imported["artifact_id"])
    by_digest = resolve_archived_source(paths, imported["digest_hex"])

    assert by_occurrence.occurrence_id == imported["occurrence_id"]
    assert by_artifact.artifact_id == imported["artifact_id"] == by_digest.artifact_id
    assert by_occurrence.capture.digest_hex == imported["digest_hex"]
    assert by_occurrence.capture.byte_length == by_artifact.capture.byte_length


def test_resolves_validated_file_id_bound_to_occurrence_and_provenance(
    active_root: _ActiveRoot,
) -> None:
    imported = _import_workbook(active_root)
    provenance_id = _provenance_id(active_root.database, imported["occurrence_id"])
    _insert_file_id(
        active_root.database,
        occurrence_id=imported["occurrence_id"],
        file_id="241027_1",
        provenance_id=provenance_id,
        digest_hex=imported["digest_hex"],
    )

    resolved = resolve_archived_source(_generation_paths(active_root), "241027_1")

    assert resolved.occurrence_id == imported["occurrence_id"]
    assert resolved.artifact_id == imported["artifact_id"]


def test_unknown_and_json_selectors_fail_closed(active_root: _ActiveRoot) -> None:
    _import_workbook(active_root)
    paths = _generation_paths(active_root)

    with pytest.raises(SourceLookupError, match="unknown"):
        resolve_archived_source(paths, "missing-file")
    with pytest.raises(SourceLookupError, match="unknown"):
        resolve_archived_source(paths, '{"file_id":"241027_1"}')


def test_unbound_file_id_is_rejected(active_root: _ActiveRoot) -> None:
    imported = _import_workbook(active_root)
    _insert_file_id(
        active_root.database,
        occurrence_id=imported["occurrence_id"],
        file_id="unbound-1",
        provenance_id=None,
        digest_hex=imported["digest_hex"],
    )

    with pytest.raises(SourceLookupError, match="not bound"):
        resolve_archived_source(_generation_paths(active_root), "unbound-1")


def test_ambiguous_file_id_is_rejected(active_root: _ActiveRoot) -> None:
    first = _import_workbook(active_root)
    second = _import_workbook(active_root, extra="other")
    _insert_file_id(
        active_root.database,
        occurrence_id=first["occurrence_id"],
        file_id="dup-id",
        provenance_id=_provenance_id(active_root.database, first["occurrence_id"]),
        digest_hex=first["digest_hex"],
    )
    _insert_file_id(
        active_root.database,
        occurrence_id=second["occurrence_id"],
        file_id="dup-id",
        provenance_id=_provenance_id(active_root.database, second["occurrence_id"]),
        digest_hex=second["digest_hex"],
    )

    with pytest.raises(SourceLookupError, match="ambiguous"):
        resolve_archived_source(_generation_paths(active_root), "dup-id")
