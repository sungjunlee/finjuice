"""Status evidence materialized from one validated repository snapshot."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from finjuice.pipeline.storage.sqlite.errors import ObjectCorruptionError
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.storage.sqlite.transaction_scopes import _object, _source_scopes


@dataclass(frozen=True)
class ConfigHeadSnapshot:
    """An explicitly selected config revision, including its source parse status."""

    config_kind: str
    revision_id: str
    parsed_status: str
    updated_at: str
    content: bytes


@dataclass(frozen=True)
class ImportOccurrenceSnapshot:
    """An occurrence and proven origin; aliases never replace its UUID identity."""

    occurrence_id: str
    artifact_id: str
    occurrence_kind: str
    original_filename: str | None
    imported_at: str | None
    parser_version: str | None
    origin: Literal["native_import", "migration_capture", "other"]
    legacy_file_ids: tuple[str, ...]


@dataclass(frozen=True)
class LegacyImportHistorySnapshot:
    """One source-backed history row; its timestamp remains the original text."""

    legacy_file_id: str | None
    imported_at: str | None
    occurrence_id: str
    provenance_id: str
    source_row: int


@dataclass(frozen=True)
class StatusReadSnapshot:
    """Detached transactions, configs, and import evidence from one revision."""

    info: RepositoryInfo
    transactions: TransactionReadSnapshot
    rules: ConfigHeadSnapshot | None
    goals: ConfigHeadSnapshot | None
    source_occurrences: tuple[ImportOccurrenceSnapshot, ...]
    legacy_import_history: tuple[LegacyImportHistorySnapshot, ...] = ()


def status_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths, transactions: TransactionReadSnapshot
) -> StatusReadSnapshot:
    """Read status-only evidence while reusing already verified rules bytes."""
    return StatusReadSnapshot(
        transactions.info,
        transactions,
        _head(connection, paths, "rules", transactions.rules_content),
        _head(connection, paths, "goals"),
        _occurrences(connection),
        _legacy_history(connection),
    )


def _head(
    connection: sqlite3.Connection,
    paths: GenerationPaths,
    kind: str,
    known_content: bytes | None = None,
) -> ConfigHeadSnapshot | None:
    row = connection.execute(
        "SELECT revision.entity_id, revision.parsed_status, head.updated_at, "
        "revision.source_artifact_id, artifact.byte_length FROM config_heads AS head "
        "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
        "JOIN source_artifacts AS artifact "
        "ON artifact.source_artifact_id = revision.source_artifact_id WHERE head.config_kind = ?",
        (kind,),
    ).fetchone()
    if row is None:
        return None
    content = known_content
    if content is None:
        artifact = SourceObjectStore(paths).verify(row[3], row[4])
        content = (paths.root / artifact.relative_path).read_bytes()
    if len(content) != row[4] or "sha256:" + hashlib.sha256(content).hexdigest() != row[3]:
        raise ObjectCorruptionError("Canonical configuration changed while being read.")
    return ConfigHeadSnapshot(kind, row[0], row[1], row[2], content)


def _occurrences(connection: sqlite3.Connection) -> tuple[ImportOccurrenceSnapshot, ...]:
    migrated = {
        row[0]
        for row in connection.execute(
            "SELECT entity_id FROM migration_identities WHERE record_kind = 'source_occurrence'"
        )
    }
    completed = _completed_imports(connection)
    aliases = _file_ids(connection)
    rows = connection.execute(
        "SELECT entity_id, source_artifact_id, occurrence_kind, original_filename, "
        "imported_at, parser_version FROM source_occurrences ORDER BY entity_id"
    )
    result = []
    for row in rows:
        origin: Literal["native_import", "migration_capture", "other"] = "other"
        if row[0] in migrated:
            origin = "migration_capture"
        elif row[2] == "exact_xlsx_import" and completed.get(row[0]) == 1:
            origin = "native_import"
        result.append(
            ImportOccurrenceSnapshot(
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                origin,
                tuple(sorted(aliases.get(row[0], set()))),
            )
        )
    return tuple(result)


def _completed_imports(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    invalid: set[str] = set()
    rows = connection.execute(
        "SELECT provenance.source_occurrence_id, provenance.source_coordinate_json, "
        "payload.payload_json FROM record_provenance AS provenance "
        "JOIN source_occurrences AS occurrence "
        "ON occurrence.entity_id = provenance.source_occurrence_id "
        "JOIN legacy_payloads AS payload ON payload.provenance_id = provenance.provenance_id "
        "WHERE occurrence.occurrence_kind = 'exact_xlsx_import'"
    )
    for occurrence, coordinate_json, payload_json in rows:
        try:
            coordinate, payload = json.loads(coordinate_json), json.loads(payload_json)
        except (TypeError, ValueError):
            invalid.add(occurrence)
            continue
        if not isinstance(coordinate, dict) or not isinstance(payload, dict):
            continue
        if coordinate.get("kind") != "exact_xlsx_import_manifest":
            continue
        if (
            coordinate.get("role") == "root"
            and payload.get("manifest_kind") == "finjuice.exact_xlsx_import.v1"
            and payload.get("status") == "completed"
        ):
            counts[occurrence] = counts.get(occurrence, 0) + 1
        else:
            invalid.add(occurrence)
    return {key: value for key, value in counts.items() if key not in invalid}


def _file_ids(connection: sqlite3.Connection) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    rows = connection.execute(
        "SELECT COALESCE(provenance.source_occurrence_id, occurrence.entity_id), "
        "mapping.identifier_value "
        "FROM legacy_identifiers AS mapping "
        "LEFT JOIN record_provenance AS provenance "
        "ON provenance.provenance_id = mapping.provenance_id "
        "LEFT JOIN source_occurrences AS occurrence ON occurrence.entity_id = mapping.entity_id "
        "WHERE mapping.identifier_kind = 'file_id' AND NOT EXISTS "
        "(SELECT 1 FROM legacy_identifier_supersessions AS supersession "
        "WHERE supersession.previous_mapping_id = mapping.mapping_id)"
    )
    for occurrence, value in rows:
        if occurrence is not None:
            aliases.setdefault(occurrence, set()).add(value)
    return aliases


def _legacy_history(connection: sqlite3.Connection) -> tuple[LegacyImportHistorySnapshot, ...]:
    sources = {
        key: value
        for key, value in _source_scopes(connection).items()
        if value[1].get("root") == "data" and value[1].get("path") == "metadata/import_history.csv"
    }
    if not sources:
        return ()
    rows = connection.execute(
        "SELECT provenance.source_occurrence_id, provenance.provenance_id, "
        "provenance.source_coordinate_json, provenance.legacy_locator_json, "
        "identity.canonical_locator_json, identity.capture_manifest_digest, payload.payload_json "
        "FROM observations AS observation JOIN migration_identities AS identity "
        "ON identity.entity_id = observation.entity_id AND identity.record_kind = 'observation' "
        "JOIN record_provenance AS provenance "
        "ON provenance.source_occurrence_id = observation.source_occurrence_id "
        "AND provenance.source_coordinate_json = identity.canonical_locator_json "
        "JOIN legacy_payloads AS payload ON payload.provenance_id = provenance.provenance_id "
        "ORDER BY provenance.source_occurrence_id, provenance.provenance_id"
    )
    result = [_history_row(tuple(row), sources.get(row[0])) for row in rows]
    return tuple(
        sorted(
            (row for row in result if row is not None),
            key=lambda row: (row.occurrence_id, row.source_row, row.provenance_id),
        )
    )


def _history_row(
    row: tuple[Any, ...], source: tuple[str, dict[str, Any]] | None
) -> LegacyImportHistorySnapshot | None:
    if source is None:
        return None
    capture, file_locator = source
    locator, payload = _object(row[2]), _object(row[6])
    if locator is None or payload is None or row[5] != capture:
        return None
    if locator != _object(row[3]) or locator != _object(row[4]):
        return None
    ordinal = locator.get("row")
    if type(ordinal) is not int or ordinal < 1 or {**locator, "row": None} != file_locator:
        return None
    values = _history_values(payload)
    if values is None:
        return None
    return LegacyImportHistorySnapshot(values[0], values[1], row[0], row[1], ordinal)


def _history_values(payload: dict[str, Any]) -> tuple[str | None, str | None] | None:
    columns, values = payload.get("columns"), payload.get("values")
    if not isinstance(columns, list) or not isinstance(values, list) or len(columns) != len(values):
        return None
    if any(not isinstance(column, str) for column in columns) or len(set(columns)) != len(columns):
        return None
    fields = dict(zip(columns, values, strict=True))
    if not {"file_id", "imported_at"} <= fields.keys():
        return None
    selected = (fields["file_id"], fields["imported_at"])
    if any(value is not None and not isinstance(value, str) for value in selected):
        return None
    return selected
