"""Strict row coverage against the original captured history CSV."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.storage.sqlite.history_reads import LegacyHistoryRecord
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.history_sources import HistorySource


def _object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid history evidence object.")
    return parsed


def legacy_history_records(
    connection: sqlite3.Connection, source: HistorySource
) -> tuple[LegacyHistoryRecord, ...]:
    """Require every logical CSV ordinal to have matching preserved row evidence."""
    from finjuice.pipeline.migration.adapters.csv_rows import rows

    header = next(csv.reader(io.StringIO(source.content.decode("utf-8-sig")), strict=True), None)
    if (
        not header
        or len(header) != len(set(header))
        or "" in header
        or not {"file_id", "imported_at"} <= set(header)
    ):
        raise ValueError("Invalid history CSV header.")
    if connection.execute(
        "SELECT 1 FROM migration_dispositions AS disposition "
        "JOIN record_provenance AS prov USING (provenance_id) "
        "WHERE prov.source_occurrence_id = ? AND disposition.reason = 'csv_parse_failed'",
        (source.occurrence_id,),
    ).fetchone():
        raise ValueError("History source has incomplete parse evidence.")
    expected = {ordinal: (payload, fields) for ordinal, payload, fields in rows(source.content)}
    preserved = _preserved_rows(connection, source)
    observations = _observation_rows(connection, source)
    if set(expected) != set(preserved) or set(expected) != set(observations):
        raise ValueError("History record coverage differs from captured CSV.")
    result = []
    for ordinal, (payload, fields) in expected.items():
        provenance_id, stored = preserved[ordinal]
        if fields is None or stored != payload:
            raise ValueError("History record differs from captured CSV.")
        result.append(
            LegacyHistoryRecord(
                source.occurrence_id, source.artifact_id, provenance_id, ordinal, fields, payload
            )
        )
    return tuple(result)


def _row_ordinal(coordinate: str, source: HistorySource) -> int | None:
    locator = _object(coordinate)
    ordinal = locator.get("row")
    if set(locator) != set(source.locator) or {**locator, "row": None} != source.locator:
        raise ValueError("History locator does not match its source.")
    if ordinal is not None and (type(ordinal) is not int or ordinal < 1):
        raise ValueError("Invalid history record ordinal.")
    return ordinal


def _preserved_rows(
    connection: sqlite3.Connection, source: HistorySource
) -> dict[int, tuple[str, dict[str, Any]]]:
    result = {}
    for provenance, coordinate, legacy, payload_id, payload in connection.execute(
        "SELECT prov.provenance_id, prov.source_coordinate_json, prov.legacy_locator_json, "
        "payload.payload_id, payload.payload_json FROM record_provenance AS prov "
        "LEFT JOIN legacy_payloads AS payload USING (provenance_id) "
        "WHERE prov.source_occurrence_id = ?",
        (source.occurrence_id,),
    ):
        ordinal = _row_ordinal(coordinate, source)
        if _object(coordinate) != _object(legacy):
            raise ValueError("History provenance locators disagree.")
        if ordinal is None:
            continue  # File-level proof is checked by verified_history_sources.
        locator = _object(coordinate)
        if provenance != migration_entity_id(
            source.capture_digest, "provenance", locator
        ) or payload_id != migration_entity_id(source.capture_digest, "legacy_payload", locator):
            raise ValueError("History preserved record identity does not match its source.")
        if ordinal in result:
            raise ValueError("Duplicate history record provenance.")
        result[ordinal] = (provenance, _object(payload))
    return result


def _observation_rows(connection: sqlite3.Connection, source: HistorySource) -> set[int]:
    result: set[int] = set()
    identifiers: set[str] = set()
    for identifier, coordinate, capture in connection.execute(
        "SELECT observation.entity_id, identity.canonical_locator_json, "
        "identity.capture_manifest_digest "
        "FROM observations AS observation LEFT JOIN migration_identities AS identity "
        "ON identity.entity_id = observation.entity_id AND identity.record_kind = 'observation' "
        "WHERE observation.source_occurrence_id = ?",
        (source.occurrence_id,),
    ):
        ordinal = _row_ordinal(coordinate, source)
        if (
            ordinal is None
            or ordinal in result
            or capture != source.capture_digest
            or identifier
            != migration_entity_id(source.capture_digest, "observation", _object(coordinate))
        ):
            raise ValueError("Invalid history observation identity.")
        result.add(ordinal)
        identifiers.add(identifier)
    preserved_ids = set()
    for identifier, coordinate in connection.execute(
        "SELECT entity_id, canonical_locator_json FROM migration_identities "
        "WHERE record_kind = 'observation' AND capture_manifest_digest = ?",
        (source.capture_digest,),
    ):
        locator = _object(coordinate)
        if (
            locator.get("root") == source.locator["root"]
            and locator.get("path") == source.locator["path"]
        ):
            _row_ordinal(coordinate, source)
            preserved_ids.add(identifier)
    if preserved_ids != identifiers:
        raise ValueError("History observation identity coverage differs.")
    return result
