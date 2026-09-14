"""Confirm extracted asset values without replacing or inventing original evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping
from uuid import UUID

from finjuice.pipeline.storage.sqlite.asset_meanings import AssetMeaningDecision, validate_decision
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import (
    AssetSnapshotRecord,
    ObservationRecord,
    ProvenanceRecord,
    SourceOccurrenceRecord,
)

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext


@dataclass(frozen=True)
class AssetObservationDecision:
    account_id: str
    resource_id: str
    field: str
    as_of: str
    scope_state: Literal["complete", "partial", "unknown"]
    measure_kind: str
    currency: str
    net_worth_sign: int
    evidence: Mapping[str, Any]
    row_index: int | None = None


def _identity(seed: str, role: str) -> str:
    # UUIDv8 uses application-defined SHA-256 bytes; UUIDv5 is reserved for migration origins.
    raw = bytearray(
        hashlib.sha256(f"finjuice.intake.asset.v1/{seed}/{role}".encode()).digest()[:16]
    )
    raw[6] = (raw[6] & 15) | 128
    raw[8] = (raw[8] & 63) | 128
    return str(UUID(bytes=bytes(raw)))


def _input(
    connection: sqlite3.Connection, context: MutationContext, proposal_id: str
) -> tuple[Any, str]:
    validate_entity_id(proposal_id)
    row = connection.execute(
        "SELECT a.source_artifact_id,e.payload_digest,e.payload_json,o.occurrence_json,"
        "o.received_at,s.byte_length FROM agent_intake_proposals p "
        "JOIN agent_intake_extractions e ON e.extraction_id=p.extraction_id "
        "JOIN agent_intake_occurrences o ON o.occurrence_id=e.occurrence_id "
        "JOIN agent_intake_artifacts a ON a.intake_artifact_id=o.intake_artifact_id "
        "JOIN source_artifacts s ON s.source_artifact_id=a.source_artifact_id "
        "WHERE p.proposal_id=?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Asset observation needs a persisted intake extraction.")
    SourceObjectStore(context.authority.paths).verify(row[0], expected_size=row[5])
    detail = json.loads(row[3])
    source_kind = {
        "screenshot": "screenshot",
        "description": "manual",
        "xlsx": "institution_export",
    }.get(detail.get("source_kind"))
    if source_kind is None or detail.get("uncertainties"):
        raise MutationValidationError("Resolve source kind and extraction uncertainties first.")
    return row, source_kind


def _value(command: AssetObservationDecision, payload: Any) -> ExactValue:
    if not isinstance(command.field, str) or not command.field:
        raise MutationValidationError("An explicit extraction field is required.")
    if command.row_index is not None:
        if (
            type(command.row_index) is not int
            or command.row_index < 0
            or not isinstance(payload, list)
        ):
            raise MutationValidationError("Extraction row must be an explicit zero-based index.")
        if command.row_index >= len(payload):
            raise MutationValidationError("Extraction row is missing.")
        payload = payload[command.row_index]
    if not isinstance(payload, dict) or command.field not in payload:
        raise MutationValidationError("Amount must reference a stored extraction field.")
    amount = payload[command.field]
    if type(amount) not in (str, int):
        raise MutationValidationError(
            "Extracted amount must use exact text or integer, never float."
        )
    if command.measure_kind == "holding_quantity":
        raise MutationValidationError("Quantity intake requires a separate explicit unit contract.")
    return ExactValue.from_lexical(str(amount), value_kind="money", currency=command.currency)


def apply_asset_observation(
    connection: sqlite3.Connection,
    context: MutationContext,
    proposal_id: str,
    decision: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Apply persisted extraction inside the caller's human-confirmed mutation transaction.

    ``field`` is a literal dictionary key; optional ``row_index`` selects a top-level list row.
    Account and resource UUIDs must already exist. Corrections use asset_meaning explicitly.
    """
    try:
        command = AssetObservationDecision(**dict(decision))
        for identifier in (command.account_id, command.resource_id):
            validate_entity_id(identifier)
        if (
            connection.execute(
                "SELECT 1 FROM accounts WHERE entity_id=?", (command.account_id,)
            ).fetchone()
            is None
            or connection.execute(
                "SELECT 1 FROM resources WHERE entity_id=?", (command.resource_id,)
            ).fetchone()
            is None
        ):
            raise MutationValidationError(
                "Explicit existing account and resource identities are required."
            )
        row, source_kind = _input(connection, context, proposal_id)
        value = _value(command, json.loads(row[2]))
        coordinate = {
            "artifact_id": row[0],
            "extraction_digest": row[1],
            "field": command.field,
            "row_index": command.row_index,
        }
        seed = json.dumps(coordinate, sort_keys=True, separators=(",", ":"))
        ids = {
            role: _identity(seed, role)
            for role in ("source", "provenance", "observation", "value", "asset")
        }
        meaning = AssetMeaningDecision(
            source_entity_id=ids["asset"],
            value_id=ids["value"],
            account_id=command.account_id,
            resource_id=command.resource_id,
            measure_kind=command.measure_kind,
            source_kind=source_kind,
            as_of=command.as_of,
            scope_state=command.scope_state,
            evidence=command.evidence,
            original_currency=command.currency,
            net_worth_sign=command.net_worth_sign,
        )
        existing = connection.execute(
            "SELECT account_id,resource_id,snapshot_date FROM asset_snapshots WHERE entity_id=?",
            (ids["asset"],),
        ).fetchone()
        if existing is None:
            context.add_source_occurrence(
                SourceOccurrenceRecord(
                    ids["source"],
                    row[0],
                    "confirmed_intake_asset",
                    imported_at=row[4],
                    parser_version="intake.asset.v1",
                )
            )
            context.add_provenance(
                ProvenanceRecord(
                    ids["provenance"],
                    ids["source"],
                    coordinate,
                    coordinate,
                    parser_version="intake.asset.v1",
                )
            )
            context.add_observation(
                ObservationRecord(
                    ids["observation"],
                    ids["source"],
                    command.as_of,
                    command.as_of,
                    row[4],
                    command.scope_state,
                    "confirmed",
                )
            )
            context.add_exact_value(ids["value"], value, provenance_id=ids["provenance"])
            context.add_asset_snapshot(
                AssetSnapshotRecord(
                    ids["asset"],
                    ids["observation"],
                    ids["provenance"],
                    command.account_id,
                    command.resource_id,
                    None,
                    ids["value"],
                    command.as_of,
                )
            )
            applied: Mapping[str, Any] = context.confirm_asset_meaning(meaning)
        else:
            validate_decision(connection, meaning)
            applied = _reuse(connection, command, value, ids, source_kind, existing)
        return {
            "source_entity_id": ids["asset"],
            "observation_id": ids["observation"],
            "value_id": ids["value"],
            "assertion_id": applied["assertion_id"],
            "reused": existing is not None,
        }
    except (TypeError, KeyError, ValueError) as exc:
        raise MutationValidationError(
            "Asset observation decision or stored extraction is invalid."
        ) from exc


def _reuse(
    connection: sqlite3.Connection,
    command: AssetObservationDecision,
    value: ExactValue,
    ids: Mapping[str, str],
    source_kind: str,
    existing: Any,
) -> Mapping[str, Any]:
    expected = (command.account_id, command.resource_id, command.as_of)
    exact = connection.execute(
        "SELECT coefficient,scale,lexical FROM exact_values WHERE value_id=?", (ids["value"],)
    ).fetchone()
    if tuple(existing) != expected or tuple(exact or ()) != (
        value.coefficient,
        value.scale,
        value.lexical,
    ):
        raise MutationConflictError("Existing observation requires an explicit correction.")
    from finjuice.pipeline.storage.sqlite.asset_reports import _heads

    cursor = connection.execute(
        "SELECT * FROM asset_meaning_assertions WHERE source_entity_id=?", (ids["asset"],)
    )
    columns = [column[0] for column in cursor.description]
    meanings = [dict(zip(columns, row, strict=True)) for row in cursor]
    heads = [row for row in _heads(meanings) if row["confirmation_state"] == "confirmed"]
    fields = (
        "value_id",
        "account_id",
        "resource_id",
        "measure_kind",
        "source_kind",
        "as_of",
        "scope_state",
        "confirmation_state",
        "original_currency",
        "net_worth_sign",
    )
    expected_head = (
        ids["value"],
        command.account_id,
        command.resource_id,
        command.measure_kind,
        source_kind,
        command.as_of,
        command.scope_state,
        "confirmed",
        command.currency,
        command.net_worth_sign,
    )
    if (
        len(heads) != 1
        or tuple(heads[0][field] for field in fields) != expected_head
        or json.loads(heads[0]["evidence_json"]) != dict(command.evidence)
        or heads[0]["fx_value_id"] is not None
    ):
        raise MutationConflictError(
            "Existing asset meaning differs; use explicit typed correction."
        )
    return {"assertion_id": heads[0]["assertion_id"]}
