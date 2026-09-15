"""Canonical local JSON statement adapter: envelope, evidence and explicit decisions.

The adapter never guesses. A record only becomes an economic transaction when
the caller supplies an explicit ``create`` decision *and* the statement's
account key already resolves to a confirmed account source binding. Everything
else is preserved as durable pending evidence (artifact, occurrence, provenance,
raw payload and an unconfirmed observation) so a later explicit decision can
complete it without inventing a duplicate. Amounts are parsed lexically; no
float, currency or ownership inference ever happens here.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationValidationError,
)
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
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

STATEMENT_SCHEMA_VERSION = "finjuice.statement.v1"
STATEMENT_OCCURRENCE_KIND = "canonical_json_statement"
STATEMENT_FAMILY = "statement"
STATEMENT_ACCOUNT_NAMESPACE = "statement.json.account_key.v1"
RECORD_COORDINATE_KIND = "canonical_json_record"
COVERAGE_KINDS = ("full", "partial", "historical")
_SCOPE_STATE: dict[str, Literal["complete", "partial", "unknown"]] = {
    "full": "complete",
    "partial": "partial",
    "historical": "complete",
}
_TYPES = ("expense", "income", "transfer", "other")
_ACTIONS = ("create", "link", "pending")
_IDENTITY = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CREDENTIAL = re.compile(
    r"pass(word|phrase)|secret|token|api[_-]?key|credential|authorization|cookie"
    r"|session[_-]?id|access[_-]?key|private[_-]?key|otp|cvv|pin[_-]?code",
    re.IGNORECASE,
)
_ENVELOPE_FIELDS = (
    "source_identity",
    "schema_version",
    "parser_version",
    "original_hash",
    "as_of",
    "collected_at",
    "coverage",
    "currency",
    "idempotency_key",
)


class _Lexical(str):
    """A JSON number kept as its exact source text so it is never a float."""


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


def _reject_constant(name: str) -> Any:
    raise MutationValidationError("Statement JSON cannot contain a non-finite constant.")


def parse_document(content: bytes) -> dict[str, Any]:
    """Parse exact JSON bytes lexically and reject credential-like fields."""
    if not isinstance(content, bytes) or not content:
        raise MutationValidationError("Statement document requires exact original bytes.")
    try:
        document = json.loads(
            content.decode("utf-8"),
            parse_float=_Lexical,
            parse_int=_Lexical,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise MutationValidationError("Statement document is not valid UTF-8 JSON.") from exc
    if not isinstance(document, Mapping):
        raise MutationValidationError("Statement document must be a JSON object.")
    _reject_credentials(document)
    return _validate_envelope(document)


def _reject_credentials(node: Any, depth: int = 0) -> None:
    if depth > 32:
        raise MutationValidationError("Statement document nesting is too deep.")
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(key, str) and _CREDENTIAL.search(key):
                raise MutationValidationError(
                    "Statement document carries a credential-like field and was rejected."
                )
            _reject_credentials(value, depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _reject_credentials(value, depth + 1)


def _text(value: Any, message: str, *, limit: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise MutationValidationError(message)
    return value


def _timestamp(value: Any, message: str) -> str:
    text = _text(value, message, limit=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MutationValidationError(message) from exc
    if parsed.tzinfo is None:
        raise MutationValidationError(message)
    return text


def _day(value: Any, message: str) -> str:
    text = _text(value, message, limit=10)
    try:
        if date.fromisoformat(text).isoformat() != text:
            raise ValueError(text)
    except ValueError as exc:
        raise MutationValidationError(message) from exc
    return text


def _currency(value: Any) -> str:
    text = _text(value, "Statement currency must be an explicit ISO code.", limit=3)
    if len(text) != 3 or not text.isupper() or not text.isalpha():
        raise MutationValidationError("Statement currency must be an explicit ISO code.")
    return text


def _validate_envelope(document: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in (*_ENVELOPE_FIELDS, "records") if field not in document]
    if missing:
        raise MutationValidationError("Statement envelope is missing required fields.")
    if document["schema_version"] != STATEMENT_SCHEMA_VERSION:
        raise MutationValidationError("Statement schema version is not supported.")
    identity = _text(document["source_identity"], "Statement source identity must be explicit.")
    if not _IDENTITY.fullmatch(identity):
        raise MutationValidationError("Statement source identity must be explicit.")
    if document["coverage"] not in COVERAGE_KINDS:
        raise MutationValidationError("Statement coverage must be full, partial or historical.")
    if not _DIGEST.fullmatch(str(document["original_hash"])):
        raise MutationValidationError("Statement original hash must be sha256:<64 hex>.")
    records = document["records"]
    if not isinstance(records, list) or not records:
        raise MutationValidationError("Statement must carry at least one explicit record.")
    return _envelope_payload(document, identity, records)


def _envelope_payload(
    document: Mapping[str, Any], identity: str, records: list[Any]
) -> dict[str, Any]:
    return {
        "source_identity": identity,
        "schema_version": STATEMENT_SCHEMA_VERSION,
        "parser_version": _text(document["parser_version"], "Parser version must be explicit."),
        "original_hash": str(document["original_hash"]),
        "as_of": _timestamp(document["as_of"], "Statement as_of requires a timezone."),
        "collected_at": _timestamp(
            document["collected_at"], "Statement collected_at requires a timezone."
        ),
        "coverage": str(document["coverage"]),
        "currency": _currency(document["currency"]),
        "idempotency_key": _text(document["idempotency_key"], "Producer key must be explicit."),
        "records": records,
    }


@dataclass(frozen=True)
class _Row:
    """One validated statement record and its explicit decision."""

    index: int
    external_id: str
    account_key: str
    amount: ExactValue
    currency: str
    occurred_on: str
    occurred_at: str | None
    type_norm: str
    action: str
    target: str | None
    reason: str | None
    payload: Mapping[str, Any]

    def content_digest(self) -> str:
        """Digest exactly the immutable meaning of this record."""
        body = _canonical(
            [
                self.external_id,
                self.account_key,
                self.amount.coefficient,
                self.amount.scale,
                self.currency,
                self.occurred_on,
                self.occurred_at,
                self.type_norm,
            ]
        )
        return hashlib.sha256(body.encode("ascii")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _amount(value: Any, currency: str) -> ExactValue:
    if type(value) is not str:
        raise MutationValidationError("Statement amount must be an exact decimal string.")
    try:
        return ExactValue.from_lexical(value, value_kind="money", currency=currency)
    except Exception as exc:
        raise MutationValidationError("Statement amount is not an exact decimal.") from exc


def _decision(record: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    decision = record.get("decision")
    if decision is None:
        return "pending", None, "decision_absent"
    if not isinstance(decision, Mapping) or decision.get("action") not in _ACTIONS:
        raise MutationValidationError("Statement decision action must be explicit.")
    action = str(decision["action"])
    reason = _text(decision["reason"], "Reason must be text.") if "reason" in decision else None
    if action != "link":
        return action, None, reason
    target = _text(
        decision.get("transaction_id"), "Link decision requires a transaction id.", limit=36
    )
    validate_entity_id(target)
    return action, target, None


def _row(index: int, record: Any, envelope: Mapping[str, Any]) -> _Row:
    if not isinstance(record, Mapping):
        raise MutationValidationError("Statement record must be a JSON object.")
    currency = _currency(record.get("currency", envelope["currency"]))
    occurred_at = record.get("occurred_at")
    action, target, reason = _decision(record)
    return _Row(
        index=index,
        external_id=_text(record.get("external_transaction_id"), "External id must be explicit."),
        account_key=_text(record.get("source_account_key"), "Source account key must be explicit."),
        amount=_amount(record.get("amount"), currency),
        currency=currency,
        occurred_on=_day(record.get("occurred_on"), "Record occurred_on must be YYYY-MM-DD."),
        occurred_at=None
        if occurred_at is None
        else _timestamp(occurred_at, "Record occurred_at requires a timezone."),
        type_norm=str(record["type"]) if record.get("type") in _TYPES else _reject_type(),
        action=action,
        target=target,
        reason=reason,
        payload=dict(record),
    )


def _reject_type() -> str:
    raise MutationValidationError(
        "Statement record type must be expense, income, transfer or other."
    )


def plan_rows(envelope: Mapping[str, Any]) -> tuple[_Row, ...]:
    """Validate every record before any mutation so a malformed batch changes nothing."""
    rows = tuple(_row(index, record, envelope) for index, record in enumerate(envelope["records"]))
    seen: set[str] = set()
    for row in rows:
        if row.external_id in seen:
            raise MutationValidationError("Statement repeats one external transaction id.")
        seen.add(row.external_id)
    return rows


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


def import_statement(
    connection: sqlite3.Connection, context: MutationContext, command: StatementImport
) -> dict[str, Any]:
    """Preserve exact statement bytes and apply only explicitly decided economic records."""
    envelope = parse_document(command.content)
    rows = plan_rows(envelope)
    resolved = _resolve_rows(connection, envelope, rows)
    if command.preview:
        return _preview_result(rows, resolved)
    store = SourceObjectStore(context.authority.paths)
    artifact = store.publish(io.BytesIO(command.content))
    context.register_source_artifact(artifact)
    original_id = _publish_original(context, store, command, envelope)
    occurrence_id = _occurrence(context, artifact.artifact_id, envelope, command.imported_at)
    counts = _Counts([], [], [], [])
    for row in rows:
        _apply_row(context, envelope, row, resolved[row.index], occurrence_id, artifact, counts)
    return _result(envelope, artifact, original_id, occurrence_id, counts, rows)


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
