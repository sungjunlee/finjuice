"""Read-only resolver for archived source occurrence, artifact, or file_id."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.storage.sqlite.errors import (
    IdentifierError,
    MutationValidationError,
    ObjectStoreError,
)
from finjuice.pipeline.storage.sqlite.exact_import import ExactWorkbookCapture, capture_exact_xlsx
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_COLUMNS = (
    "SELECT occurrence.entity_id, artifact.source_artifact_id, "
    "artifact.digest_hex, artifact.byte_length, occurrence.original_filename "
)


class SourceLookupError(MutationValidationError):
    """A source selector is unknown, ambiguous, or not capture-bound."""


@dataclass(frozen=True)
class ResolvedSource:
    """One verified archived workbook ready for exact import."""

    occurrence_id: str
    artifact_id: str
    digest_hex: str
    byte_length: int
    original_filename: str | None
    capture: ExactWorkbookCapture


def resolve_archived_source(paths: GenerationPaths, selector: str) -> ResolvedSource:
    """Resolve one unambiguous archived source and capture its verified bytes."""
    kind, normalized = _classify_selector(selector)
    row = _unique_source_row(paths.database, kind, normalized)
    capture = _capture_verified(paths, row)
    return ResolvedSource(
        occurrence_id=row[0],
        artifact_id=row[1],
        digest_hex=row[2],
        byte_length=int(row[3]),
        original_filename=row[4],
        capture=capture,
    )


def _classify_selector(selector: str) -> tuple[str, str]:
    text = selector.strip()
    if not text:
        raise SourceLookupError("Source selector is unknown.")
    if _ARTIFACT_RE.fullmatch(text):
        return "artifact", text
    if _DIGEST_RE.fullmatch(text):
        return "artifact", f"sha256:{text}"
    try:
        return "occurrence", validate_entity_id(text)
    except IdentifierError:
        return "file_id", text


def _unique_source_row(
    database: Path, kind: str, selector: str
) -> tuple[str, str, str, int, str | None]:
    rows = _fetch_source_rows(database, kind, selector)
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise SourceLookupError("Source selector is ambiguous.")
    if kind == "file_id" and _unbound_file_id_exists(database, selector):
        raise SourceLookupError(
            "Migrated file_id is not bound to source occurrence capture evidence."
        )
    raise SourceLookupError("Source selector is unknown.")


def _fetch_source_rows(
    database: Path, kind: str, selector: str
) -> list[tuple[str, str, str, int, str | None]]:
    sql, parameters = _source_query(kind, selector)
    with _read_only(database) as connection:
        raw_rows = connection.execute(sql, parameters).fetchall()
    return [_source_row(row) for row in raw_rows]


def _source_query(kind: str, selector: str) -> tuple[str, tuple[str, ...]]:
    if kind == "occurrence":
        return _OCCURRENCE_SQL, (selector,)
    if kind == "artifact":
        return _ARTIFACT_SQL, (selector, selector.removeprefix("sha256:"))
    return _FILE_ID_SQL, (selector,)


def _source_row(row: tuple[object, ...]) -> tuple[str, str, str, int, str | None]:
    filename = row[4]
    byte_length = row[3]
    if not isinstance(byte_length, int) or isinstance(byte_length, bool):
        raise SourceLookupError("Archived source byte length is malformed.")
    return (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        byte_length,
        None if filename is None else str(filename),
    )


def _unbound_file_id_exists(database: Path, selector: str) -> bool:
    with _read_only(database) as connection:
        found = connection.execute(_FILE_ID_EXISTS_SQL, (selector,)).fetchone()
    return found is not None


def _capture_verified(
    paths: GenerationPaths, row: tuple[str, str, str, int, str | None]
) -> ExactWorkbookCapture:
    occurrence_id, artifact_id, digest_hex, byte_length, filename = row
    del occurrence_id
    try:
        verified = SourceObjectStore(paths).verify(artifact_id, expected_size=byte_length)
    except ObjectStoreError as exc:
        raise SourceLookupError("Archived source object could not be verified.") from exc
    capture = capture_exact_xlsx(paths.object_path(verified.digest_hex), filename=filename)
    if capture.digest_hex != digest_hex or capture.byte_length != byte_length:
        raise SourceLookupError("Captured source does not match the archived artifact.")
    if capture.artifact_id != artifact_id:
        raise SourceLookupError("Captured source does not match the archived artifact.")
    return capture


@contextmanager
def _read_only(database: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()


_OCCURRENCE_SQL = (
    _SOURCE_COLUMNS + "FROM source_occurrences AS occurrence "
    "JOIN source_artifacts AS artifact "
    "ON artifact.source_artifact_id = occurrence.source_artifact_id "
    "WHERE occurrence.entity_id = ? "
    "ORDER BY occurrence.entity_id"
)
_ARTIFACT_SQL = (
    _SOURCE_COLUMNS + "FROM source_artifacts AS artifact "
    "JOIN source_occurrences AS occurrence "
    "ON occurrence.source_artifact_id = artifact.source_artifact_id "
    "WHERE artifact.source_artifact_id = ? OR artifact.digest_hex = ? "
    "ORDER BY occurrence.entity_id"
)
_FILE_ID_SQL = (
    _SOURCE_COLUMNS + "FROM legacy_identifiers AS mapping "
    "JOIN source_occurrences AS occurrence ON occurrence.entity_id = mapping.entity_id "
    "JOIN source_artifacts AS artifact "
    "ON artifact.source_artifact_id = occurrence.source_artifact_id "
    "JOIN record_provenance AS provenance "
    "ON provenance.provenance_id = mapping.provenance_id "
    "AND provenance.source_occurrence_id = occurrence.entity_id "
    "LEFT JOIN legacy_identifier_supersessions AS supersession "
    "ON supersession.previous_mapping_id = mapping.mapping_id "
    "WHERE mapping.identifier_kind = 'file_id' AND mapping.identifier_value = ? "
    "AND mapping.provenance_id IS NOT NULL "
    "AND length(mapping.capture_manifest_digest) = 64 "
    "AND supersession.previous_mapping_id IS NULL "
    "ORDER BY occurrence.entity_id"
)
_FILE_ID_EXISTS_SQL = (
    "SELECT mapping.mapping_id FROM legacy_identifiers AS mapping "
    "WHERE mapping.identifier_kind = 'file_id' AND mapping.identifier_value = ?"
)

__all__ = ["ResolvedSource", "SourceLookupError", "resolve_archived_source"]
