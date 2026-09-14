"""Native history verifies completion closure and preserves explicit occurrence aliases."""

from __future__ import annotations

import sqlite3

from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    MANIFEST_COORDINATE_KIND,
    MANIFEST_KIND,
    OCCURRENCE_KIND,
)
from finjuice.pipeline.storage.sqlite.exact_import.lookup import load_completed_exact_imports
from finjuice.pipeline.storage.sqlite.history_reads import NativeImportHistoryRecord
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths


def native_history_records(
    connection: sqlite3.Connection, paths: GenerationPaths
) -> tuple[NativeImportHistoryRecord, ...]:
    """Verify completion once per digest and preserve occurrence-sourced metadata."""
    markers = _manifest_inventory(connection)
    result = []
    completed = {}
    for occurrence, artifact, filename, imported_at, digest, size in connection.execute(
        "SELECT occurrence.entity_id, occurrence.source_artifact_id, occurrence.original_filename, "
        "occurrence.imported_at, artifact.digest_hex, artifact.byte_length "
        "FROM source_occurrences AS occurrence LEFT JOIN source_artifacts AS artifact "
        "ON artifact.source_artifact_id = occurrence.source_artifact_id "
        "WHERE occurrence.occurrence_kind = ? "
        "ORDER BY occurrence.imported_at, occurrence.entity_id",
        (OCCURRENCE_KIND,),
    ):
        if digest not in completed:
            SourceObjectStore(paths).verify(artifact, size)
            completed[digest] = load_completed_exact_imports(connection, digest)
        records = completed[digest]
        if (
            len(records) != 1
            or records[0]["occurrence_id"] != occurrence
            or records[0]["artifact_id"] != artifact
        ):
            raise ValueError("Native history completion is missing or ambiguous.")
        record = records[0]
        result.append(
            NativeImportHistoryRecord(
                occurrence,
                artifact,
                record["provenance_id"],
                filename,
                imported_at,
                dict(record["payload"]["counts"]),
                _direct_file_ids(connection, occurrence),
            )
        )
    if markers != {(record.occurrence_id, record.provenance_id) for record in result}:
        raise ValueError("Native history manifest inventory does not match its occurrences.")
    return tuple(result)


def _direct_file_ids(connection: sqlite3.Connection, occurrence: str) -> tuple[str, ...]:
    """Preserve only explicit active aliases for the verified occurrence entity."""
    aliases = set()
    for value, provenance, source in connection.execute(
        "SELECT mapping.identifier_value, mapping.provenance_id, prov.source_occurrence_id "
        "FROM legacy_identifiers AS mapping LEFT JOIN record_provenance AS prov "
        "ON prov.provenance_id = mapping.provenance_id "
        "WHERE mapping.entity_id = ? AND mapping.identifier_kind = 'file_id' "
        "AND NOT EXISTS (SELECT 1 FROM legacy_identifier_supersessions AS supersession "
        "WHERE supersession.previous_mapping_id = mapping.mapping_id)",
        (occurrence,),
    ):
        if provenance is not None and source != occurrence:
            raise ValueError("Native history alias provenance does not match its occurrence.")
        aliases.add(value)
    return tuple(sorted(aliases))


def _manifest_inventory(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    """Cross-check surviving explicit markers, independently of occurrence kind."""
    markers = set()
    for provenance, occurrence, kind, coordinate_kind, payload_kind in connection.execute(
        "SELECT prov.provenance_id, prov.source_occurrence_id, occurrence.occurrence_kind, "
        "json_extract(prov.source_coordinate_json, '$.kind'), "
        "json_extract(payload.payload_json, '$.manifest_kind') "
        "FROM record_provenance AS prov LEFT JOIN legacy_payloads AS payload "
        "ON payload.provenance_id = prov.provenance_id "
        "LEFT JOIN source_occurrences AS occurrence "
        "ON occurrence.entity_id = prov.source_occurrence_id "
        "WHERE json_extract(prov.source_coordinate_json, '$.kind') = ? "
        "UNION "
        "SELECT prov.provenance_id, prov.source_occurrence_id, occurrence.occurrence_kind, "
        "json_extract(prov.source_coordinate_json, '$.kind'), "
        "json_extract(payload.payload_json, '$.manifest_kind') "
        "FROM legacy_payloads AS payload LEFT JOIN record_provenance AS prov "
        "ON prov.provenance_id = payload.provenance_id "
        "LEFT JOIN source_occurrences AS occurrence "
        "ON occurrence.entity_id = prov.source_occurrence_id "
        "WHERE json_extract(payload.payload_json, '$.manifest_kind') = ?",
        (MANIFEST_COORDINATE_KIND, MANIFEST_KIND),
    ):
        if (
            provenance is None
            or occurrence is None
            or kind != OCCURRENCE_KIND
            or coordinate_kind != MANIFEST_COORDINATE_KIND
            or payload_kind != MANIFEST_KIND
        ):
            raise ValueError("Native history manifest marker is inconsistent.")
        markers.add((occurrence, provenance))
    return markers
