"""Canonical local JSON statement adapter: envelope, evidence and explicit decisions.

The adapter never guesses. A record only becomes an economic transaction when
the caller supplies an explicit ``create`` decision *and* the statement's
account key already resolves to a confirmed account source binding. Everything
else is preserved as durable pending evidence (artifact, occurrence, provenance,
raw payload and an unconfirmed observation) so a later explicit decision can
complete it without inventing a duplicate.

Parse and row canonicalization live in
:mod:`finjuice.pipeline.statements.canonical_parse` and are re-exported here
so existing callers can keep importing public names from this module.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from finjuice.pipeline.statements.canonical_parse import (
    _ENVELOPE_FIELDS,
    COVERAGE_KINDS,  # noqa: F401 — re-exported public parse constant
    STATEMENT_SCHEMA_VERSION,
    _Row,
    parse_document,
    plan_rows,
)
from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationValidationError,
)
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import (
    ObservationRecord,
    ProvenanceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
    TransactionSourceLinkRecord,
)

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext

STATEMENT_OCCURRENCE_KIND = "canonical_json_statement"
STATEMENT_FAMILY = "statement"
STATEMENT_ACCOUNT_NAMESPACE = "statement.json.account_key.v1"
RECORD_COORDINATE_KIND = "canonical_json_record"
_SCOPE_STATE: dict[str, Literal["complete", "partial", "unknown"]] = {
    "full": "complete",
    "partial": "partial",
    "historical": "complete",
}


@dataclass(frozen=True)
class StatementImport:
    """One local JSON statement document plus its optional upstream original."""

    content: bytes
    imported_at: str
    original: bytes | None = None
    preview: bool = False

    def payload(self) -> dict[str, Any]:
        """Bind the exact document bytes and declared identity to the retry key."""
        envelope = parse_document(self.content)
        return {
            "document_digest": hashlib.sha256(self.content).hexdigest(),
            "original_supplied": self.original is not None,
            "imported_at": self.imported_at,
            **{field: envelope[field] for field in _ENVELOPE_FIELDS},
            "record_count": len(envelope["records"]),
        }


_MAPPING_SQL = """
SELECT p.provenance_id,
       json_extract(p.source_coordinate_json, '$.content_digest'),
       l.transaction_id
FROM record_provenance p
LEFT JOIN transaction_source_links l ON l.provenance_id = p.provenance_id
WHERE json_extract(p.source_coordinate_json, '$.family') = ?
  AND json_extract(p.source_coordinate_json, '$.source_identity') = ?
  AND json_extract(p.source_coordinate_json, '$.external_transaction_id') = ?
ORDER BY p.provenance_id
"""

_TARGET_SQL = """
SELECT t.entity_id, t.account_id, t.date_raw, e.coefficient, e.scale,
       m.currency_code, m.currency_unknown
FROM transactions t
JOIN money_values m ON m.value_id = t.amount_value_id
JOIN exact_values e ON e.value_id = t.amount_value_id
WHERE t.entity_id = ?
"""


def _existing_mapping(
    connection: sqlite3.Connection, identity: str, external_id: str
) -> tuple[str | None, set[str]]:
    rows = connection.execute(_MAPPING_SQL, (STATEMENT_FAMILY, identity, external_id)).fetchall()
    digests = {str(row[1]) for row in rows if row[1] is not None}
    linked = [str(row[2]) for row in rows if row[2] is not None]
    return (linked[0] if linked else None), digests


def _assert_link_target(connection: sqlite3.Connection, row: _Row, account_id: str) -> None:
    target = connection.execute(_TARGET_SQL, (row.target,)).fetchone()
    if target is None:
        raise MutationValidationError("Link decision target transaction does not exist.")
    if str(target[1]) != account_id or str(target[2])[:10] != row.occurred_on:
        raise MutationValidationError("Link decision target account or date does not match.")
    if target[6] or str(target[5]) != row.currency:
        raise MutationValidationError("Link decision target currency does not match.")
    if (str(target[3]), int(target[4])) != (row.amount.coefficient, row.amount.scale):
        raise MutationValidationError("Link decision target amount is not the exact same value.")


def _occurrence(
    context: MutationContext, artifact_id: str, envelope: Mapping[str, Any], imported_at: str
) -> str:
    occurrence_id = new_entity_id()
    context.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact_id,
            occurrence_kind=STATEMENT_OCCURRENCE_KIND,
            imported_at=imported_at,
            parser_version=str(envelope["parser_version"]),
            source_schema_version=STATEMENT_SCHEMA_VERSION,
        )
    )
    return occurrence_id


def _record_provenance(
    context: MutationContext,
    occurrence_id: str,
    artifact_id: str,
    envelope: Mapping[str, Any],
    row: _Row,
) -> str:
    provenance_id = new_entity_id()
    coordinate = {
        "family": STATEMENT_FAMILY,
        "kind": RECORD_COORDINATE_KIND,
        "index": row.index,
        "source_identity": envelope["source_identity"],
        "external_transaction_id": row.external_id,
        "content_digest": row.content_digest(),
    }
    context.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=occurrence_id,
            source_coordinate=coordinate,
            legacy_locator={"artifact_id": artifact_id, "locator_version": 1, **coordinate},
            parser_version=str(envelope["parser_version"]),
            source_schema_version=STATEMENT_SCHEMA_VERSION,
        )
    )
    context.add_legacy_payload(
        provenance_id,
        {
            "family": STATEMENT_FAMILY,
            "coverage": envelope["coverage"],
            "record": dict(row.payload),
        },
    )
    return provenance_id


def _observation(
    context: MutationContext,
    occurrence_id: str,
    envelope: Mapping[str, Any],
    row: _Row,
    *,
    confirmed: bool,
) -> str:
    observation_id = new_entity_id()
    context.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=occurrence_id,
            observed_at=row.occurred_at,
            effective_at=row.occurred_on,
            collected_at=str(envelope["collected_at"]),
            scope_state=_SCOPE_STATE[str(envelope["coverage"])],
            confirmation_state="confirmed" if confirmed else "unconfirmed",
        )
    )
    return observation_id


def _transaction(
    context: MutationContext, row: _Row, account_id: str, ids: tuple[str, str, str]
) -> str:
    transaction_id, observation_id, provenance_id = ids
    amount_id = new_entity_id()
    context.add_exact_value(amount_id, row.amount, provenance_id=provenance_id)
    known = row.occurred_at is not None
    context.add_transaction(
        TransactionRecord(
            transaction_id=transaction_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=account_id,
            amount_value_id=amount_id,
            date_raw=row.occurred_on,
            time_raw=str(row.occurred_at)[11:19] if known else "",
            datetime_raw=str(row.occurred_at) if known else row.occurred_on,
            type_raw=str(row.payload.get("type")),
            type_norm=row.type_norm,
            account_text=row.account_key,
            merchant_raw=_optional(row.payload.get("description")),
            memo_raw=_optional(row.payload.get("memo")),
            timezone_state="known" if known else "unknown",
        )
    )
    return transaction_id


def _optional(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _link(
    context: MutationContext,
    transaction_id: str,
    provenance_id: str,
    observation_id: str,
    kind: str,
) -> None:
    context.add_transaction_source_link(
        TransactionSourceLinkRecord(
            link_id=new_entity_id(),
            transaction_id=transaction_id,
            provenance_id=provenance_id,
            observation_id=observation_id,
            link_kind=kind,  # type: ignore[arg-type]
        )
    )


@dataclass
class _Counts:
    """Outcome classification for one statement collection."""

    created: list[str]
    linked: list[str]
    reused: list[str]
    pending: list[str]

    def as_dict(self) -> dict[str, int]:
        return {
            "created": len(self.created),
            "linked": len(self.linked),
            "reused": len(self.reused),
            "pending": len(self.pending),
        }


def _resolve_rows(
    connection: sqlite3.Connection, envelope: Mapping[str, Any], rows: Sequence[_Row]
) -> dict[int, dict[str, Any]]:
    """Resolve bindings, prior mappings and link targets before writing anything."""
    identity = str(envelope["source_identity"])
    resolved: dict[int, dict[str, Any]] = {}
    for row in rows:
        binding = resolve_account_binding_for(connection, row.account_key)
        mapped, digests = _existing_mapping(connection, identity, row.external_id)
        if digests and row.content_digest() not in digests:
            raise MutationConflictError(
                "Statement record content changed for an already preserved external id."
            )
        if row.action == "link" and mapped is not None and row.target != mapped:
            raise MutationConflictError(
                "Statement external id is already mapped to a different transaction."
            )
        if row.action == "link" and mapped is None:
            _assert_link_target(connection, row, _required_account(binding))
        resolved[row.index] = {"binding": binding, "mapped": mapped}
    return resolved


def resolve_account_binding_for(connection: sqlite3.Connection, account_key: str) -> Any:
    """Resolve one statement account key through the confirmed binding registry."""
    from finjuice.pipeline.storage.sqlite.account_bindings import resolve_account_binding

    return resolve_account_binding(connection, STATEMENT_ACCOUNT_NAMESPACE, account_key)


def _required_account(binding: Any) -> str:
    if binding.status != "confirmed" or binding.account_id is None:
        raise MutationValidationError(
            "An explicit decision requires a confirmed account source binding."
        )
    return str(binding.account_id)


_APPLIED_SQL = """
SELECT art.source_artifact_id, occ.entity_id
FROM source_occurrences AS occ
JOIN source_artifacts AS art ON art.source_artifact_id = occ.source_artifact_id
WHERE art.digest_hex = ? AND occ.occurrence_kind = ?
ORDER BY occ.entity_id
"""


def import_statement(
    connection: sqlite3.Connection, context: MutationContext, command: StatementImport
) -> dict[str, Any]:
    """Preserve exact statement bytes and apply only explicitly decided economic records."""
    envelope = parse_document(command.content)
    rows = plan_rows(envelope)
    if command.preview:
        return _preview_statement(connection, command, envelope, rows)
    resolved = _resolve_rows(connection, envelope, rows)
    store = SourceObjectStore(context.authority.paths)
    artifact = store.publish(io.BytesIO(command.content))
    context.register_source_artifact(artifact)
    original_id = _publish_original(context, store, command, envelope)
    occurrence_id = _occurrence(context, artifact.artifact_id, envelope, command.imported_at)
    counts = _Counts([], [], [], [])
    for row in rows:
        _apply_row(context, envelope, row, resolved[row.index], occurrence_id, artifact, counts)
    return _result(envelope, artifact, original_id, occurrence_id, counts, rows)


def _preview_statement(
    connection: sqlite3.Connection,
    command: StatementImport,
    envelope: Mapping[str, Any],
    rows: Sequence[_Row],
) -> dict[str, Any]:
    """Preview new work, or report an already-recorded identical document as a noop."""
    applied = _applied_statement(connection, command.content)
    if applied is not None:
        return _history_skipped_preview(applied, len(rows))
    return _preview_result(rows, _resolve_rows(connection, envelope, rows))


def _applied_statement(connection: sqlite3.Connection, content: bytes) -> tuple[str, str] | None:
    """Return the first statement occurrence bound to these exact document bytes."""
    digest_hex = hashlib.sha256(content).hexdigest()
    row = connection.execute(_APPLIED_SQL, (digest_hex, STATEMENT_OCCURRENCE_KIND)).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def _history_skipped_preview(applied: tuple[str, str], record_count: int) -> dict[str, Any]:
    """Match the XLSX completed-preview contract: identical bytes are already recorded."""
    artifact_id, occurrence_id = applied
    return {
        "artifact_id": artifact_id,
        "completed": False,
        "counts": {"created": 0, "linked": 0, "reused": record_count, "pending": 0},
        "noop": True,
        "occurrence_id": occurrence_id,
    }


def _preview_result(
    rows: Sequence[_Row], resolved: Mapping[int, Mapping[str, Any]]
) -> dict[str, Any]:
    """Return write-path counts without publishing artifacts or mutation entries."""
    counts = _Counts([], [], [], [])
    for row in rows:
        _tally_row(counts, row, resolved[row.index])
    return {
        "artifact_id": None,
        "completed": False,
        "counts": counts.as_dict(),
        "noop": False,
        "occurrence_id": None,
    }


def _tally_row(counts: _Counts, row: _Row, state: Mapping[str, Any]) -> None:
    """Classify one resolved row the same way the write path would, without writing."""
    mapped = state["mapped"]
    binding = state["binding"]
    decided = row.action in {"create", "link"} and binding.status == "confirmed"
    if mapped is not None:
        counts.reused.append(row.external_id)
        return
    if not decided:
        counts.pending.append(row.external_id)
        return
    if row.action == "link":
        assert row.target is not None
        counts.linked.append(row.target)
        return
    counts.created.append(row.external_id)


def _publish_original(
    context: MutationContext,
    store: SourceObjectStore,
    command: StatementImport,
    envelope: Mapping[str, Any],
) -> str | None:
    if command.original is None:
        return None
    digest = "sha256:" + hashlib.sha256(command.original).hexdigest()
    if digest != envelope["original_hash"]:
        raise MutationValidationError("Supplied original bytes do not match the declared hash.")
    artifact = store.publish(io.BytesIO(command.original))
    context.register_source_artifact(artifact)
    return artifact.artifact_id


def _apply_row(
    context: MutationContext,
    envelope: Mapping[str, Any],
    row: _Row,
    state: Mapping[str, Any],
    occurrence_id: str,
    artifact: Any,
    counts: _Counts,
) -> None:
    mapped = state["mapped"]
    binding = state["binding"]
    decided = row.action in {"create", "link"} and binding.status == "confirmed"
    provenance_id = _record_provenance(context, occurrence_id, artifact.artifact_id, envelope, row)
    observation_id = _observation(
        context, occurrence_id, envelope, row, confirmed=decided or mapped is not None
    )
    if mapped is not None:
        _link(context, mapped, provenance_id, observation_id, "duplicate_evidence")
        counts.reused.append(row.external_id)
        return
    if not decided:
        counts.pending.append(row.external_id)
        return
    _apply_decision(context, row, str(binding.account_id), provenance_id, observation_id, counts)


def _apply_decision(
    context: MutationContext,
    row: _Row,
    account_id: str,
    provenance_id: str,
    observation_id: str,
    counts: _Counts,
) -> None:
    if row.action == "link":
        assert row.target is not None
        _link(context, row.target, provenance_id, observation_id, "duplicate_evidence")
        counts.linked.append(row.target)
        return
    transaction_id = _transaction(
        context, row, account_id, (new_entity_id(), observation_id, provenance_id)
    )
    _link(context, transaction_id, provenance_id, observation_id, "origin")
    counts.created.append(transaction_id)


def _result(
    envelope: Mapping[str, Any],
    artifact: Any,
    original_id: str | None,
    occurrence_id: str,
    counts: _Counts,
    rows: Sequence[_Row],
) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "original_artifact_id": original_id,
        "occurrence_id": occurrence_id,
        "source_identity": envelope["source_identity"],
        "coverage": envelope["coverage"],
        "as_of": envelope["as_of"],
        "collected_at": envelope["collected_at"],
        "currency": envelope["currency"],
        "record_count": len(rows),
        "counts": counts.as_dict(),
        "created_transaction_ids": list(counts.created),
        "linked_transaction_ids": list(counts.linked),
        "reused_external_ids": list(counts.reused),
        "pending_external_ids": list(counts.pending),
        "noop": not (counts.created or counts.linked),
    }


_EVIDENCE_SQL = """
SELECT json_extract(p.source_coordinate_json, '$.source_identity'),
       json_extract(p.source_coordinate_json, '$.external_transaction_id'),
       json_extract(p.source_coordinate_json, '$.content_digest'),
       p.provenance_id, p.source_occurrence_id, o.source_artifact_id, o.imported_at,
       l.transaction_id, l.link_kind, b.confirmation_state, b.scope_state, b.collected_at
FROM record_provenance p
JOIN source_occurrences o ON o.entity_id = p.source_occurrence_id
LEFT JOIN transaction_source_links l ON l.provenance_id = p.provenance_id
LEFT JOIN observations b ON b.entity_id = l.observation_id
WHERE json_extract(p.source_coordinate_json, '$.family') = ?
ORDER BY p.provenance_id
"""

_EVIDENCE_COLUMNS = (
    "source_identity",
    "external_transaction_id",
    "content_digest",
    "provenance_id",
    "occurrence_id",
    "source_artifact_id",
    "imported_at",
    "transaction_id",
    "link_kind",
    "confirmation_state",
    "scope_state",
    "collected_at",
)


def statement_evidence(
    connection: sqlite3.Connection, *, source_identity: str | None = None
) -> dict[str, Any]:
    """Read every preserved statement record, its mapping and its pending state."""
    rows = [
        dict(zip(_EVIDENCE_COLUMNS, row, strict=True))
        for row in connection.execute(_EVIDENCE_SQL, (STATEMENT_FAMILY,))
        if source_identity is None or row[0] == source_identity
    ]
    for row in rows:
        row["status"] = "pending" if row["transaction_id"] is None else "mapped"
    occurrences = sorted({str(row["occurrence_id"]) for row in rows})
    mapped_keys = {
        (row["source_identity"], row["external_transaction_id"])
        for row in rows
        if row["transaction_id"] is not None
    }
    pending = [
        row
        for row in rows
        if (row["source_identity"], row["external_transaction_id"]) not in mapped_keys
    ]
    return {
        "records": rows,
        "occurrence_ids": occurrences,
        "pending_external_ids": sorted({str(row["external_transaction_id"]) for row in pending}),
        "record_count": len(rows),
    }
