"""Parse and canonicalize local JSON statement documents.

Lexical JSON parsing, envelope validation and row planning live here so
:mod:`finjuice.pipeline.statements.canonical` can keep sqlite apply and
publish on a separate path. Amounts are parsed lexically; no float, currency
or ownership inference ever happens here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

STATEMENT_SCHEMA_VERSION = "finjuice.statement.v1"
COVERAGE_KINDS = ("full", "partial", "historical")
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
