"""Pinned display partition scopes without changing transaction dates or identity."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

READ_SCOPE_POLICY = "legacy_partition_scope.v1"
_PARTITION = re.compile(r"transactions/([0-9]{4})/(0[1-9]|1[0-2])/transactions\.csv\Z")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_ISO_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")


@dataclass(frozen=True)
class TransactionScope:
    """One internal display scope, keyed by authoritative transaction identity."""

    transaction_id: str
    month: str | None
    included: bool
    source_row: int | None = None


_SOURCE_SQL = """
SELECT occurrence.entity_id, occurrence.source_artifact_id, occurrence.legacy_path,
       artifact.byte_length, identity.capture_manifest_digest,
       identity.canonical_locator_json, provenance.source_coordinate_json,
       provenance.legacy_locator_json, payload.payload_json
FROM source_occurrences AS occurrence
JOIN source_artifacts AS artifact USING (source_artifact_id)
JOIN migration_identities AS identity ON identity.entity_id = occurrence.entity_id
    AND identity.record_kind = 'source_occurrence'
JOIN record_provenance AS provenance ON provenance.source_occurrence_id = occurrence.entity_id
JOIN legacy_payloads AS payload USING (provenance_id)
WHERE occurrence.occurrence_kind = 'legacy_capture'
    AND json_type(provenance.source_coordinate_json, '$.row') = 'null'
"""
_ROW_SQL = """
SELECT txn.entity_id, observation.effective_at, provenance.source_occurrence_id,
       observation.source_occurrence_id, provenance.source_coordinate_json,
       provenance.legacy_locator_json, payload.payload_json,
       txn_identity.capture_manifest_digest, txn_identity.canonical_locator_json,
       obs_identity.capture_manifest_digest, obs_identity.canonical_locator_json,
       occurrence_identity.capture_manifest_digest
FROM transactions AS txn
JOIN observations AS observation ON observation.entity_id = txn.observation_id
JOIN record_provenance AS provenance ON provenance.provenance_id = txn.provenance_id
LEFT JOIN legacy_payloads AS payload ON payload.provenance_id = txn.provenance_id
LEFT JOIN migration_identities AS txn_identity ON txn_identity.entity_id = txn.entity_id
LEFT JOIN migration_identities AS obs_identity ON obs_identity.entity_id = observation.entity_id
LEFT JOIN migration_identities AS occurrence_identity
    ON occurrence_identity.entity_id = provenance.source_occurrence_id
ORDER BY txn.entity_id
"""


def _object(value: str | None) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value) if value is not None else None
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _month(locator: dict[str, Any]) -> str | None:
    if locator.get("root") != "data" or not isinstance(locator.get("path"), str):
        return None
    match = _PARTITION.fullmatch(locator["path"])
    if match is None or match[1] == "0000":
        return None
    return f"{match[1]}-{match[2]}"


def _source_scopes(connection: sqlite3.Connection) -> dict[str, tuple[str, dict[str, Any]]]:
    result = {}
    for (
        occurrence,
        artifact,
        path,
        size,
        capture,
        identity,
        coordinate,
        legacy,
        payload,
    ) in connection.execute(_SOURCE_SQL):
        locator, raw = _object(identity), _object(payload)
        if locator is None or raw is None or set(locator) != {"root", "path", "row"}:
            continue
        if locator["row"] is not None or locator["path"] != path:
            continue
        if _object(coordinate) != locator or _object(legacy) != locator:
            continue
        if raw != {
            "artifact_id": artifact,
            "byte_length": size,
            "locator": locator,
            "encoding": "original_bytes",
        }:
            continue
        result[occurrence] = (capture, locator)
    return result


def _native_month(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        if _ISO_DATE.fullmatch(value):
            parsed = date.fromisoformat(value)
        elif _ISO_DATETIME.match(value):
            parsed = datetime.fromisoformat(value).date()
        else:
            return None
    except ValueError:
        return None
    return parsed.isoformat()[:7]


def _migration_month(
    row: tuple[Any, ...], sources: dict[str, tuple[str, dict[str, Any]]]
) -> str | None:
    source = sources.get(row[2])
    locator, raw = _object(row[4]), _object(row[6])
    if source is None or locator is None or raw is None or row[2] != row[3]:
        return None
    capture, file_locator = source
    if not (row[7] == row[9] == row[11] == capture):
        return None
    if not (locator == _object(row[5]) == _object(row[8]) == _object(row[10])):
        return None
    if type(locator.get("row")) is not int or locator["row"] < 1:
        return None
    if {**locator, "row": None} != file_locator or not (
        isinstance(raw.get("columns"), list)
        and isinstance(raw.get("cells"), list)
        and isinstance(raw.get("values"), list)
        and isinstance(raw.get("raw_record"), str)
    ):
        return None
    return _month(locator)


def transaction_scopes(
    connection: sqlite3.Connection, transaction_ids: tuple[str, ...]
) -> tuple[tuple[TransactionScope, ...], tuple[str, ...]]:
    """Resolve scopes and empty source partitions from the same reader connection."""
    sources = _source_scopes(connection)
    months = {month for _, locator in sources.values() if (month := _month(locator)) is not None}
    scopes = {}
    for raw in connection.execute(_ROW_SQL):
        row = tuple(raw)
        migrated = any(row[index] is not None for index in (7, 9, 11))
        month = _migration_month(row, sources) if migrated else _native_month(row[1])
        # Only a proven migration locator supplies the one-based CSV record ordinal.
        source_row = json.loads(row[4])["row"] if migrated and month is not None else None
        scopes[row[0]] = TransactionScope(
            row[0], month, not migrated or month is not None, source_row
        )
        if month is not None:
            months.add(month)
    return tuple(scopes[identifier] for identifier in transaction_ids), tuple(sorted(months))
