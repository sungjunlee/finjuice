"""Verify legacy history source inventory against preserved capture manifests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.backup.manifest import compute_manifest_digest, validate_manifest_structure
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

_HISTORY = "metadata/import_history.csv"
_ERROR = "Canonical history source evidence is incomplete or inconsistent."


@dataclass(frozen=True)
class HistorySource:
    """Verified original bytes and private file-level capture coordinates."""

    occurrence_id: str
    artifact_id: str
    capture_digest: str
    locator: dict[str, Any]
    content: bytes


def verified_history_sources(
    connection: sqlite3.Connection, paths: GenerationPaths
) -> tuple[HistorySource, ...]:
    """Read and verify manifest-backed source coverage on the caller's connection."""
    try:
        return _verified(connection, paths)
    except Exception:
        raise RepositoryIntegrityError(_ERROR) from None


def _object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(_ERROR)
    return value


def _one(connection: sqlite3.Connection, sql: str, values: tuple[Any, ...]) -> tuple[Any, ...]:
    rows = connection.execute(sql, values).fetchall()
    if len(rows) != 1:
        raise ValueError(_ERROR)
    return tuple(rows[0])


def _content(connection: sqlite3.Connection, paths: GenerationPaths, artifact: str) -> bytes:
    size, digest, relative = _one(
        connection,
        "SELECT byte_length,digest_hex,object_path FROM source_artifacts "
        "WHERE source_artifact_id=?",
        (artifact,),
    )
    verified = SourceObjectStore(paths).verify(artifact, size)
    if verified.relative_path != relative or verified.digest_hex != digest:
        raise ValueError(_ERROR)
    content = paths.object_path(digest).read_bytes()
    if len(content) != size or "sha256:" + hashlib.sha256(content).hexdigest() != artifact:
        raise ValueError(_ERROR)
    return content


def _identity(
    connection: sqlite3.Connection, entity: str, digest: str, kind: str, locator: dict[str, Any]
) -> None:
    actual = _one(
        connection,
        "SELECT capture_manifest_digest,record_kind,canonical_locator_json "
        "FROM migration_identities WHERE entity_id=?",
        (entity,),
    )
    if actual[:2] != (digest.removeprefix("sha256:"), kind) or _object(actual[2]) != locator:
        raise ValueError(_ERROR)
    if entity != migration_entity_id(digest, kind, locator):
        raise ValueError(_ERROR)


def _manifests(connection: sqlite3.Connection, paths: GenerationPaths) -> dict[str, dict[str, Any]]:
    result = {}
    anchors = connection.execute(
        "SELECT entity_id,source_artifact_id FROM source_occurrences "
        "WHERE occurrence_kind='legacy_capture_manifest'"
    ).fetchall()
    for entity, artifact in anchors:
        manifest = _object(_content(connection, paths, artifact).decode("utf-8"))
        validate_manifest_structure(manifest)
        digest = manifest["canonical_digest"]
        if compute_manifest_digest(manifest) != digest or digest.removeprefix("sha256:") in result:
            raise ValueError(_ERROR)
        _identity(connection, entity, digest, "source_occurrence", {"capture_manifest": True})
        revision = migration_entity_id(digest, "config_revision", {"baseline": True})
        baseline = _one(
            connection,
            "SELECT config_kind,source_artifact_id,source_occurrence_id,"
            "parsed_status,canonical_payload_json FROM config_revisions WHERE entity_id=?",
            (revision,),
        )
        expected = {
            "origin_kind": "legacy_current_state",
            "dataset_revision": 0,
            "capture_manifest_digest": digest,
            "revision_id": revision,
        }
        if (
            baseline[:4] != ("other", artifact, entity, "parsed")
            or _object(baseline[4]) != expected
        ):
            raise ValueError(_ERROR)
        _identity(connection, revision, digest, "config_revision", {"baseline": True})
        result[digest.removeprefix("sha256:")] = manifest
    surviving = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT capture_manifest_digest FROM migration_identities"
        )
    }
    for (raw,) in connection.execute(
        "SELECT canonical_payload_json FROM config_revisions "
        "WHERE canonical_payload_json IS NOT NULL"
    ):
        payload = _object(raw)
        if payload.get("origin_kind") == "legacy_current_state":
            surviving.add(str(payload.get("capture_manifest_digest")).removeprefix("sha256:"))
    if surviving != set(result):
        raise ValueError(_ERROR)
    for (digest,) in connection.execute(
        "SELECT identity.capture_manifest_digest FROM source_occurrences AS occurrence "
        "LEFT JOIN migration_identities AS identity ON identity.entity_id=occurrence.entity_id "
        "AND identity.record_kind='source_occurrence' "
        "WHERE occurrence.occurrence_kind='legacy_capture'"
    ):
        if digest not in result:
            raise ValueError(_ERROR)
    return result


def _source(
    connection: sqlite3.Connection, paths: GenerationPaths, digest: str, entry: dict[str, Any]
) -> HistorySource:
    locator = {"root": entry["root"], "path": entry["path"], "row": None}
    entity = migration_entity_id(digest, "source_occurrence", locator)
    artifact, kind, path = _one(
        connection,
        "SELECT source_artifact_id,occurrence_kind,legacy_path "
        "FROM source_occurrences WHERE entity_id=?",
        (entity,),
    )
    if (artifact, kind, path) != (entry["sha256"], "legacy_capture", _HISTORY):
        raise ValueError(_ERROR)
    _identity(connection, entity, digest, "source_occurrence", locator)
    rows = connection.execute(
        "SELECT provenance_id,source_coordinate_json,legacy_locator_json "
        "FROM record_provenance WHERE source_occurrence_id=?",
        (entity,),
    )
    file_rows = []
    for provenance, coordinate, legacy in rows:
        source, old = _object(coordinate), _object(legacy)
        if source.get("row") is None or old.get("row") is None:
            file_rows.append((provenance, source, old))
    if len(file_rows) != 1:
        raise ValueError(_ERROR)
    provenance, source, old = file_rows[0]
    if (
        source != locator
        or old != locator
        or provenance != migration_entity_id(digest, "provenance", locator)
    ):
        raise ValueError(_ERROR)
    payload_id, raw = _one(
        connection,
        "SELECT payload_id,payload_json FROM legacy_payloads WHERE provenance_id=?",
        (provenance,),
    )
    if payload_id != migration_entity_id(digest, "legacy_payload", locator):
        raise ValueError(_ERROR)
    expected = {
        "artifact_id": artifact,
        "byte_length": entry["size"],
        "locator": locator,
        "encoding": "original_bytes",
    }
    if _object(raw) != expected:
        raise ValueError(_ERROR)
    content = _content(connection, paths, artifact)
    if len(content) != entry["size"]:
        raise ValueError(_ERROR)
    return HistorySource(entity, artifact, digest, locator, content)


def _verified(connection: sqlite3.Connection, paths: GenerationPaths) -> tuple[HistorySource, ...]:
    manifests = _manifests(connection, paths)
    sources = []
    for digest, manifest in sorted(manifests.items()):
        for entry in manifest["entries"]:
            if entry["type"] == "file" and entry["path"] == _HISTORY:
                sources.append(_source(connection, paths, digest, entry))
    expected = {item.occurrence_id for item in sources}
    candidates = {
        row[0]
        for row in connection.execute(
            "SELECT entity_id FROM source_occurrences WHERE legacy_path=?", (_HISTORY,)
        )
    }
    for entity, raw in connection.execute(
        "SELECT entity_id,canonical_locator_json "
        "FROM migration_identities WHERE record_kind='source_occurrence'"
    ):
        if _object(raw).get("path") == _HISTORY:
            candidates.add(entity)
    for entity, coordinate, legacy in connection.execute(
        "SELECT source_occurrence_id,source_coordinate_json,legacy_locator_json "
        "FROM record_provenance"
    ):
        if _object(coordinate).get("path") == _HISTORY or _object(legacy).get("path") == _HISTORY:
            candidates.add(entity)
    if candidates != expected:
        raise ValueError(_ERROR)
    return tuple(item for item in sources if item.locator["root"] == "data")
