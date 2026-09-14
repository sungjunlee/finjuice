"""Private exact-import SQL helpers used only by MutationContext."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, Final

from finjuice.pipeline.storage.sqlite.errors import IdentifierError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    MANIFEST_COORDINATE_KIND,
    MANIFEST_KIND,
    OCCURRENCE_KIND,
)
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

JSONValue = Any
_DIGEST_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_FAMILY_COUNT_KEYS: Final = ("inserted", "quarantined", "reused", "unsupported")
_PROJECTION_TABLES: Final = (
    "overview_balances",
    "overview_cashflows",
    "overview_insurance",
    "overview_investments",
    "overview_loans",
)
_OCCURRENCE_SQL: Final = (
    "SELECT occ.entity_id FROM source_occurrences AS occ "
    "JOIN source_artifacts AS art ON art.source_artifact_id = occ.source_artifact_id "
    "WHERE art.digest_hex = ? AND occ.occurrence_kind = ? ORDER BY occ.entity_id"
)
_MANIFEST_SQL: Final = (
    "SELECT occ.entity_id, occ.source_artifact_id, prov.provenance_id, "
    "prov.source_coordinate_json, payload.payload_json "
    "FROM source_occurrences AS occ "
    "JOIN source_artifacts AS art ON art.source_artifact_id = occ.source_artifact_id "
    "JOIN record_provenance AS prov ON prov.source_occurrence_id = occ.entity_id "
    "LEFT JOIN legacy_payloads AS payload ON payload.provenance_id = prov.provenance_id "
    "WHERE art.digest_hex = ? AND occ.occurrence_kind = ? "
    "ORDER BY occ.entity_id, prov.provenance_id"
)
_IDENTITY_SQL: Final = (
    "SELECT txn.entity_id, txn.type_norm, obs.effective_at, "
    "amount.coefficient, amount.scale, money.currency_code, money.currency_unknown, "
    "txn.timezone_state, txn.time_raw, txn.date_raw "
    "FROM transactions AS txn "
    "JOIN observations AS obs ON obs.entity_id = txn.observation_id "
    "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id "
    "JOIN money_values AS money ON money.value_id = txn.amount_value_id "
    "ORDER BY txn.entity_id"
)
_TX_BOUND_SQL: Final = (
    "SELECT txn.entity_id FROM transactions AS txn "
    "JOIN observations AS obs ON obs.entity_id = txn.observation_id "
    "JOIN record_provenance AS prov ON prov.provenance_id = txn.provenance_id "
    "JOIN transaction_source_links AS link ON link.transaction_id = txn.entity_id "
    "AND link.observation_id = txn.observation_id "
    "AND link.provenance_id = txn.provenance_id AND link.link_kind = 'origin' "
    "WHERE obs.source_occurrence_id = ? AND prov.source_occurrence_id = ?"
)
_TYPED_BOUND_SQL: Final = (
    "SELECT item.entity_id FROM {table} AS item "
    "JOIN observations AS obs ON obs.entity_id = item.observation_id "
    "JOIN record_provenance AS prov ON prov.provenance_id = item.provenance_id "
    "WHERE obs.source_occurrence_id = ? AND prov.source_occurrence_id = ?"
)
_FACT_BOUND_SQL: Final = (
    "SELECT item.source_fact_id FROM {table} AS item "
    "JOIN observations AS obs ON obs.entity_id = item.observation_id "
    "JOIN record_provenance AS prov ON prov.provenance_id = item.provenance_id "
    "WHERE obs.source_occurrence_id = ? AND prov.source_occurrence_id = ?"
)


def load_completed_exact_imports(
    connection: sqlite3.Connection,
    digest_hex: str,
) -> tuple[Mapping[str, JSONValue], ...]:
    """Return one verified completed import, or fail closed on a partial marker."""
    _validate_digest_hex(digest_hex)
    occurrences = connection.execute(_OCCURRENCE_SQL, (digest_hex, OCCURRENCE_KIND)).fetchall()
    if not occurrences:
        return ()
    rows = connection.execute(_MANIFEST_SQL, (digest_hex, OCCURRENCE_KIND)).fetchall()
    records = _completed_records(occurrences, rows)
    for record in records:
        _verify_closure(connection, record)
    return records


def load_transaction_identity_snapshot(
    connection: sqlite3.Connection,
) -> tuple[Mapping[str, JSONValue], ...]:
    """Load unproven-overlap identity fields, including currency and precision."""
    rows = connection.execute(_IDENTITY_SQL).fetchall()
    return tuple(_identity_row(row) for row in rows)


def _validate_digest_hex(digest_hex: str) -> None:
    if not isinstance(digest_hex, str) or _DIGEST_HEX_RE.fullmatch(digest_hex) is None:
        raise MutationValidationError("Artifact digest must be lowercase SHA-256.")


def _completed_records(
    occurrences: Sequence[tuple[Any, ...]],
    rows: Sequence[tuple[Any, ...]],
) -> tuple[Mapping[str, JSONValue], ...]:
    manifests = tuple(item for item in (_manifest_row(row) for row in rows) if item)
    if not manifests:
        raise MutationValidationError("Exact import completion marker is missing or malformed.")
    if len(manifests) != 1 or len(occurrences) != 1:
        raise MutationValidationError("Exact import completion marker is ambiguous.")
    return manifests


def _manifest_row(row: tuple[Any, ...]) -> Mapping[str, JSONValue] | None:
    coordinate = _parse_object(row[3], "Exact import source coordinate")
    if coordinate.get("kind") != MANIFEST_COORDINATE_KIND:
        return None
    if coordinate.get("role") != "root":
        raise MutationValidationError("Exact import completion marker is malformed.")
    payload = _parse_object(row[4], "Exact import completion marker")
    if payload.get("manifest_kind") != MANIFEST_KIND or payload.get("status") != "completed":
        raise MutationValidationError("Exact import completion marker is malformed.")
    return {
        "artifact_id": str(row[1]),
        "occurrence_id": str(row[0]),
        "payload": payload,
        "provenance_id": str(row[2]),
    }


def _parse_object(value: object, label: str) -> Mapping[str, JSONValue]:
    if not isinstance(value, str):
        raise MutationValidationError(f"{label} is malformed.")
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MutationValidationError(f"{label} is malformed.") from exc
    if not isinstance(parsed, dict):
        raise MutationValidationError(f"{label} is malformed.")
    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


def _verify_closure(connection: sqlite3.Connection, record: Mapping[str, JSONValue]) -> None:
    payload = record["payload"]
    if not isinstance(payload, Mapping):
        raise MutationValidationError("Exact import completion marker is malformed.")
    ids = _payload_ids(payload)
    occurrence_id = _as_uuid(record["occurrence_id"])
    if ids["occurrence_id"] != occurrence_id:
        raise MutationValidationError("Exact import completion marker is malformed.")
    _verify_counts(payload.get("counts"), ids)
    _verify_bound_ids(connection, occurrence_id, ids)


def _payload_ids(payload: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    ids = payload.get("ids")
    if not isinstance(ids, Mapping):
        raise MutationValidationError("Exact import completion marker is malformed.")
    return {
        "asset_ids": _unique_uuids(ids.get("asset_ids")),
        "occurrence_id": _as_uuid(ids.get("occurrence_id")),
        "overview_fact_ids": _unique_uuids(ids.get("overview_fact_ids")),
        "overview_projection_ids": _unique_uuids(ids.get("overview_projection_ids")),
        "transaction_ids": _unique_uuids(ids.get("transaction_ids")),
        "uncovered_rows": _nonnegative_int(ids.get("uncovered_rows")),
    }


def _verify_counts(counts: object, ids: Mapping[str, JSONValue]) -> None:
    if not isinstance(counts, Mapping):
        raise MutationValidationError("Exact import completion marker is malformed.")
    _family_inserted(counts, "transactions", ids["transaction_ids"])
    _family_inserted(counts, "assets", ids["asset_ids"])
    overview_ids = (*ids["overview_fact_ids"], *ids["overview_projection_ids"])
    _family_inserted(counts, "overview", overview_ids)
    if _nonnegative_int(counts.get("uncovered_rows")) != ids["uncovered_rows"]:
        raise MutationValidationError("Exact import completion marker is malformed.")
    _nonnegative_int(counts.get("unknown_sheets"))


def _family_inserted(counts: Mapping[str, JSONValue], family: str, claimed: Sequence[str]) -> None:
    stored = counts.get(family)
    if not isinstance(stored, Mapping):
        raise MutationValidationError("Exact import completion marker is malformed.")
    for key in _FAMILY_COUNT_KEYS:
        _nonnegative_int(stored.get(key))
    if _nonnegative_int(stored.get("inserted")) != len(claimed):
        raise MutationValidationError("Exact import completion marker is malformed.")


def _verify_bound_ids(
    connection: sqlite3.Connection,
    occurrence_id: str,
    ids: Mapping[str, JSONValue],
) -> None:
    _require_same_ids(ids["transaction_ids"], _bound_ids(connection, _TX_BOUND_SQL, occurrence_id))
    assets = _typed_ids(connection, "asset_snapshots", occurrence_id)
    _require_same_ids(ids["asset_ids"], assets)
    facts = _typed_ids(connection, "overview_facts", occurrence_id)
    _require_same_ids(ids["overview_fact_ids"], facts)
    projections = _projection_ids(connection, occurrence_id)
    _require_same_ids(ids["overview_projection_ids"], projections)
    _require_projection_facts(connection, occurrence_id, set(ids["overview_fact_ids"]))


def _typed_ids(connection: sqlite3.Connection, table: str, occurrence_id: str) -> set[str]:
    if table not in {"asset_snapshots", "overview_facts"}:
        raise MutationValidationError("Exact import completion marker is malformed.")
    sql = _TYPED_BOUND_SQL.format(table=table)  # nosec B608
    return _bound_ids(connection, sql, occurrence_id)


def _projection_ids(connection: sqlite3.Connection, occurrence_id: str) -> set[str]:
    found: set[str] = set()
    for table in _PROJECTION_TABLES:
        sql = _TYPED_BOUND_SQL.format(table=table)  # nosec B608
        found.update(_bound_ids(connection, sql, occurrence_id))
    return found


def _require_projection_facts(
    connection: sqlite3.Connection,
    occurrence_id: str,
    fact_ids: set[str],
) -> None:
    linked: set[str] = set()
    for table in _PROJECTION_TABLES:
        sql = _FACT_BOUND_SQL.format(table=table)  # nosec B608
        linked.update(_bound_ids(connection, sql, occurrence_id))
    if not linked.issubset(fact_ids):
        raise MutationValidationError("Exact import completion marker is malformed.")


def _bound_ids(connection: sqlite3.Connection, sql: str, occurrence_id: str) -> set[str]:
    rows = connection.execute(sql, (occurrence_id, occurrence_id)).fetchall()
    return {str(row[0]) for row in rows}


def _require_same_ids(claimed: Sequence[str], actual: set[str]) -> None:
    if set(claimed) != actual:
        raise MutationValidationError("Exact import completion marker is malformed.")


def _unique_uuids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MutationValidationError("Exact import completion marker is malformed.")
    items = tuple(_as_uuid(item) for item in value)
    if len(set(items)) != len(items):
        raise MutationValidationError("Exact import completion marker is malformed.")
    return items


def _as_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise MutationValidationError("Exact import completion marker is malformed.")
    try:
        return validate_entity_id(value)
    except IdentifierError as exc:
        raise MutationValidationError("Exact import completion marker is malformed.") from exc


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise MutationValidationError("Exact import completion marker is malformed.")
    return value


def _identity_row(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, JSONValue]:
    return {
        "coefficient": str(row[3]),
        "currency_code": None if row[5] is None else str(row[5]),
        "currency_unknown": bool(row[6]),
        "date_raw": str(row[9]),
        "effective_at": None if row[2] is None else str(row[2]),
        "scale": int(row[4]),
        "time_raw": str(row[8]),
        "timezone_state": str(row[7]),
        "transaction_id": str(row[0]),
        "type_norm": str(row[1]),
    }
