"""Canonical evidence capture, exact settlement candidates and immutable decisions.

Evidence money uses purchase-positive/refund-negative values. Ledger payments
retain their original cash sign. A settlement reserves each whole occurrence;
partial matches expose the remainder and require withdrawal before regrouping.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from finjuice.pipeline.assets.money import exact_add, exact_subtract
from finjuice.pipeline.reconcile.exact_calculation import reconcile_exact
from finjuice.pipeline.reconcile.models import EvidenceItem, PaymentItem
from finjuice.pipeline.reconcile.repository import payments_from_snapshot
from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationValidationError,
    RepositoryIntegrityError,
)
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.records import ProvenanceRecord, SourceOccurrenceRecord
from finjuice.pipeline.storage.sqlite.schema_v8 import TABLE_KEYS

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext


@dataclass(frozen=True)
class PurchaseEvidence:
    external_key: str
    evidence_kind: str
    occurred_on: str
    amount: str
    currency: str
    settlement_unit: bool
    detail: Mapping[str, Any]
    parent_external_key: str | None = None
    transaction_id: str | None = None


@dataclass(frozen=True)
class EvidenceSubmission:
    source_namespace: str
    content: bytes
    received_at: str
    items: tuple[PurchaseEvidence, ...]

    def payload(self) -> dict[str, Any]:
        """Bind original bytes and complete interpretation to the durable retry key."""
        return {
            "source_namespace": self.source_namespace,
            "received_at": self.received_at,
            "source_digest": hashlib.sha256(self.content).hexdigest(),
            "items": [asdict(item) for item in self.items],
        }


@dataclass(frozen=True)
class AllocationConfirmation:
    evidence_ids: tuple[str, ...]
    payment_ids: tuple[str, ...]
    expected_residual: str
    currency: str
    reason: str
    confirmed_at: str


@dataclass(frozen=True)
class AllocationWithdrawal:
    allocation_id: str
    reason: str
    withdrawn_at: str


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "finjuice/reconcile/" + value))


def _text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MutationValidationError("Explicit nonempty reconciliation text is required.")


def _date(value: str) -> None:
    if date.fromisoformat(value).isoformat() != value:
        raise MutationValidationError("Reconciliation date must be YYYY-MM-DD.")


def _time(value: str) -> None:
    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise MutationValidationError("Reconciliation timestamp requires timezone.")


def _money(text: str, currency: str) -> ExactValue:
    return ExactValue.from_lexical(text, value_kind="money", currency=currency)


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table not in TABLE_KEYS:
        raise ValueError("Unsupported reconciliation table.")
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {', '.join(TABLE_KEYS[table])}")
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def _insert(
    connection: sqlite3.Connection, context: MutationContext, table: str, record: dict[str, Any]
) -> None:
    if table not in TABLE_KEYS:
        raise ValueError("Unsupported reconciliation table.")
    columns = {
        row[0] for row in connection.execute("SELECT name FROM pragma_table_info(?)", (table,))
    }
    if not record or not set(record) <= columns:
        raise ValueError("Record contains unsupported columns.")
    connection.execute(
        f"INSERT INTO {table} ({', '.join(record)}) VALUES ({', '.join('?' for _ in record)})",
        tuple(record.values()),
    )
    identity = "/".join(str(record[key]) for key in TABLE_KEYS[table])
    context._record(table, identity, "insert", None, record)


def _plan_evidence(
    command: EvidenceSubmission, artifact_id: str, existing: dict[str, Any]
) -> tuple[list[tuple[str, PurchaseEvidence, ExactValue, str]], set[str]]:
    planned = []
    seen: set[str] = set()
    for item in command.items:
        _text(item.external_key)
        _date(item.occurred_on)
        if item.evidence_kind not in {"purchase", "order", "line_item", "payment_evidence"}:
            raise MutationValidationError("Unsupported purchase evidence kind.")
        if type(item.settlement_unit) is not bool or not isinstance(item.detail, Mapping):
            raise MutationValidationError("Evidence requires explicit settlement scope and detail.")
        exact = _money(item.amount, item.currency)
        if item.settlement_unit and exact.to_decimal().is_zero():
            raise MutationValidationError("A settlement unit must have a nonzero exact amount.")
        identifier = _id(_json([command.source_namespace, item.external_key]))
        if identifier in seen:
            raise MutationValidationError("Duplicate submitted evidence identity.")
        seen.add(identifier)
        digest = hashlib.sha256(
            _json({"source_artifact_id": artifact_id, **asdict(item)}).encode()
        ).hexdigest()
        if identifier in existing and existing[identifier]["payload_digest"] != digest:
            raise MutationConflictError("Evidence identity is already bound to different content.")
        planned.append((identifier, item, exact, digest))
    return planned, seen


def import_evidence(
    connection: sqlite3.Connection, context: MutationContext, command: EvidenceSubmission
) -> dict[str, Any]:
    """Preserve originals and typed evidence; an identity collision never discards new content."""
    _text(command.source_namespace)
    _time(command.received_at)
    if not isinstance(command.content, bytes) or not command.content or not command.items:
        raise MutationValidationError("Reconciliation requires original bytes and explicit items.")
    artifact_id = "sha256:" + hashlib.sha256(command.content).hexdigest()
    prior_occurrences = connection.execute(
        "SELECT DISTINCT e.occurrence_id FROM reconcile_evidence e "
        "JOIN source_occurrences o ON o.entity_id=e.occurrence_id "
        "WHERE e.source_namespace=? AND o.source_artifact_id=?",
        (command.source_namespace, artifact_id),
    ).fetchall()
    if len(prior_occurrences) > 1:
        raise MutationConflictError("Evidence source has ambiguous preserved occurrences.")
    occurrence = str(prior_occurrences[0][0]) if prior_occurrences else new_entity_id()
    existing = {row["evidence_id"]: row for row in _rows(connection, "reconcile_evidence")}
    planned, seen = _plan_evidence(command, artifact_id, existing)
    if all(identifier in existing for identifier in seen):
        SourceObjectStore(context.authority.paths).verify(artifact_id)
        return {
            "source_artifact_id": artifact_id,
            "occurrence_id": occurrence,
            "evidence_ids": sorted(seen),
            "inserted_count": 0,
        }
    artifact = SourceObjectStore(context.authority.paths).publish(io.BytesIO(command.content))
    context.register_source_artifact(artifact)
    if (
        connection.execute(
            "SELECT 1 FROM source_occurrences WHERE entity_id=?", (occurrence,)
        ).fetchone()
        is None
    ):
        context.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence,
                artifact_id,
                "reconcile_evidence",
                imported_at=command.received_at,
                parser_version="explicit_reconcile.v1",
            )
        )
    count = 0
    for identifier, item, exact, digest in planned:
        if identifier in existing:
            continue
        provenance_id, value_id = new_entity_id(), new_entity_id()
        context.add_provenance(
            ProvenanceRecord(
                provenance_id,
                occurrence,
                {"external_key": item.external_key},
                {"source_namespace": command.source_namespace, "external_key": item.external_key},
            )
        )
        context.add_exact_value(value_id, exact, provenance_id=provenance_id)
        _insert(
            connection,
            context,
            "reconcile_evidence",
            {
                "evidence_id": identifier,
                "source_namespace": command.source_namespace,
                "external_key": item.external_key,
                "occurrence_id": occurrence,
                "provenance_id": provenance_id,
                "evidence_kind": item.evidence_kind,
                "parent_evidence_id": None
                if item.parent_external_key is None
                else _id(_json([command.source_namespace, item.parent_external_key])),
                "settlement_unit": int(item.settlement_unit),
                "transaction_id": item.transaction_id,
                "occurred_on": item.occurred_on,
                "amount_value_id": value_id,
                "detail_json": _json(item.detail),
                "payload_digest": digest,
                "created_changeset_id": context.changeset_id,
            },
        )
        count += 1
    return {
        "source_artifact_id": artifact_id,
        "occurrence_id": occurrence,
        "evidence_ids": sorted(seen),
        "inserted_count": count,
    }


def _value(connection: sqlite3.Connection, value_id: str) -> tuple[Decimal, str]:
    row = connection.execute(
        "SELECT e.coefficient,e.scale,e.lexical,m.currency_code,m.currency_unknown "
        "FROM exact_values e JOIN money_values m USING(value_id) WHERE value_id=?",
        (value_id,),
    ).fetchone()
    if row is None or row[4]:
        raise MutationValidationError("Settlement needs a known exact currency.")
    value = ExactValue(row[0], row[1], row[2], "money", "calculated", currency=row[3])
    return value.to_decimal(), str(row[3])


def _payments(connection: sqlite3.Connection, paths: GenerationPaths) -> tuple[PaymentItem, ...]:
    from finjuice.pipeline.storage.sqlite.schema import _read_info
    from finjuice.pipeline.storage.sqlite.transaction_reads import transaction_snapshot

    return payments_from_snapshot(
        transaction_snapshot(connection, _read_info(connection), paths)
    ).payments


def _sum(values: list[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total = exact_add(total, value)
    return total


def _selection(
    connection: sqlite3.Connection, evidence_ids: tuple[str, ...], payment_ids: tuple[str, ...]
) -> tuple[Decimal, str]:
    if (
        not evidence_ids
        or not payment_ids
        or len(set(evidence_ids)) != len(evidence_ids)
        or len(set(payment_ids)) != len(payment_ids)
    ):
        raise MutationValidationError("Allocation needs unique nonempty evidence and payment IDs.")
    evidence, payments, currencies = [], [], set()
    for identifier in evidence_ids:
        row = connection.execute(
            "SELECT amount_value_id, settlement_unit FROM reconcile_evidence WHERE evidence_id=?",
            (identifier,),
        ).fetchone()
        if row is None or row[1] != 1:
            raise MutationValidationError(
                "Allocation evidence must be an explicit settlement unit."
            )
        value, currency = _value(connection, row[0])
        evidence.append(value)
        currencies.add(currency)
    for identifier in payment_ids:
        row = connection.execute(
            "SELECT amount_value_id FROM transactions WHERE entity_id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise MutationValidationError(
                "Allocation payment must reference a canonical transaction."
            )
        value, currency = _value(connection, row[0])
        payments.append(value.copy_negate())
        currencies.add(currency)
    signs = {value > 0 for value in evidence + payments}
    if (
        len(currencies) != 1
        or len(signs) != 1
        or any(value.is_zero() for value in evidence + payments)
    ):
        raise MutationValidationError(
            "Allocation must retain one currency and purchase/refund direction."
        )
    return exact_subtract(_sum(evidence), _sum(payments)), next(iter(currencies))


def confirm_allocation(
    connection: sqlite3.Connection, context: MutationContext, command: AllocationConfirmation
) -> dict[str, Any]:
    """Reserve whole occurrences after exact residual review; never replace a prior decision."""
    _text(command.reason)
    _time(command.confirmed_at)
    allowed = {payment.payment_id for payment in _payments(connection, context.authority.paths)}
    if not set(command.payment_ids) <= allowed:
        raise MutationValidationError("Allocation payment is outside canonical included scope.")
    residual, currency = _selection(connection, command.evidence_ids, command.payment_ids)
    if (
        currency != command.currency
        or residual != _money(command.expected_residual, currency).to_decimal()
    ):
        raise MutationConflictError(
            "Reviewed allocation residual or currency does not match evidence."
        )
    for table, key, identifiers in (
        ("reconcile_allocation_evidence", "evidence_id", command.evidence_ids),
        ("reconcile_allocation_payments", "transaction_id", command.payment_ids),
    ):
        for identifier in identifiers:
            if connection.execute(
                f"SELECT 1 FROM {table} m WHERE {key}=? AND NOT EXISTS "
                "(SELECT 1 FROM reconcile_withdrawals w WHERE w.allocation_id=m.allocation_id)",
                (identifier,),
            ).fetchone():
                raise MutationConflictError(
                    "Occurrence is already reserved by a confirmed allocation."
                )
    identifier, residual_id = new_entity_id(), new_entity_id()
    context.add_exact_value(
        residual_id,
        ExactValue.from_lexical(
            str(residual),
            value_kind="money",
            origin_kind="calculated",
            currency=currency,
        ),
    )
    record = {
        "allocation_id": identifier,
        "status": "matched" if residual.is_zero() else "partial",
        "residual_value_id": residual_id,
        "reason": command.reason,
        "confirmed_at": command.confirmed_at,
        "created_changeset_id": context.changeset_id,
    }
    _insert(connection, context, "reconcile_allocations", record)
    for evidence_id in command.evidence_ids:
        _insert(
            connection,
            context,
            "reconcile_allocation_evidence",
            {"allocation_id": identifier, "evidence_id": evidence_id},
        )
    for payment_id in command.payment_ids:
        _insert(
            connection,
            context,
            "reconcile_allocation_payments",
            {"allocation_id": identifier, "transaction_id": payment_id},
        )
    return {
        "allocation_id": identifier,
        "status": record["status"],
        "residual": str(residual),
        "currency": currency,
    }


def withdraw_allocation(
    connection: sqlite3.Connection, context: MutationContext, command: AllocationWithdrawal
) -> dict[str, Any]:
    """Release an allocation with an immutable withdrawal; preserve all its original facts."""
    validate_entity_id(command.allocation_id)
    _text(command.reason)
    _time(command.withdrawn_at)
    if (
        connection.execute(
            "SELECT 1 FROM reconcile_allocations WHERE allocation_id=?", (command.allocation_id,)
        ).fetchone()
        is None
    ):
        raise MutationValidationError("Unknown reconciliation allocation.")
    if connection.execute(
        "SELECT 1 FROM reconcile_withdrawals WHERE allocation_id=?", (command.allocation_id,)
    ).fetchone():
        raise MutationConflictError("Allocation already has an immutable withdrawal.")
    identifier = new_entity_id()
    _insert(
        connection,
        context,
        "reconcile_withdrawals",
        {
            "withdrawal_id": identifier,
            "allocation_id": command.allocation_id,
            "reason": command.reason,
            "withdrawn_at": command.withdrawn_at,
            "created_changeset_id": context.changeset_id,
        },
    )
    return {
        "withdrawal_id": identifier,
        "allocation_id": command.allocation_id,
        "status": "withdrawn",
    }


def reconcile_view(
    connection: sqlite3.Connection, paths: GenerationPaths, *, window_days: int = 14
) -> dict[str, Any]:
    """One snapshot of candidates, decisions and ledger-only cash totals by currency."""
    if not connection.in_transaction:
        raise ValueError("Reconciliation view requires a read snapshot.")
    evidence = _rows(connection, "reconcile_evidence")
    allocations = _rows(connection, "reconcile_allocations")
    links = _rows(connection, "reconcile_allocation_evidence")
    payment_links = _rows(connection, "reconcile_allocation_payments")
    withdrawals = _rows(connection, "reconcile_withdrawals")
    withdrawn = {item["allocation_id"] for item in withdrawals}
    active = {item["allocation_id"] for item in allocations} - withdrawn
    used_evidence = {item["evidence_id"] for item in links if item["allocation_id"] in active}
    used_payments = {
        item["transaction_id"] for item in payment_links if item["allocation_id"] in active
    }
    payments = _payments(connection, paths)
    candidates: list[dict[str, Any]] = []
    cash: dict[str, Decimal] = {}
    evidence_items: list[EvidenceItem] = []
    for item in evidence:
        amount, currency = _value(connection, item["amount_value_id"])
        item.update(
            amount=str(amount), currency=currency, detail=json.loads(item.pop("detail_json"))
        )
        if item["settlement_unit"] and item["evidence_id"] not in used_evidence:
            evidence_items.append(
                EvidenceItem(
                    item["evidence_id"],
                    date.fromisoformat(item["occurred_on"]),
                    amount,
                    currency,
                    "order",
                    item["external_key"],
                )
            )
    for payment in payments:
        cash[payment.currency] = exact_add(cash.get(payment.currency, Decimal("0")), payment.amount)
    # The legacy matcher compares absolute money; separate signs to retain refund semantics.
    for purchase in (True, False):
        report = reconcile_exact(
            [item for item in evidence_items if (item.amount > 0) == purchase],
            [
                item
                for item in payments
                if item.payment_id not in used_payments
                and not item.amount.is_zero()
                and (item.amount < 0) == purchase
            ],
            window_days=window_days,
        )
        for group in report.groups:
            selected = next(
                item for item in evidence_items if item.evidence_id == group.evidence_ids[0]
            )
            residual = group.residual if purchase else group.residual.copy_negate()
            candidates.append(
                {
                    "evidence_ids": list(group.evidence_ids),
                    "payment_ids": list(group.payment_ids),
                    "status": group.status,
                    "residual": str(residual),
                    "currency": selected.currency,
                    "reason": group.reason,
                    "direction": "purchase" if purchase else "refund",
                }
            )
    for allocation in allocations:
        amount, currency = _value(connection, allocation["residual_value_id"])
        allocation.update(
            residual=str(amount),
            currency=currency,
            decision="withdrawn" if allocation["allocation_id"] in withdrawn else "confirmed",
            evidence_ids=[
                row["evidence_id"]
                for row in links
                if row["allocation_id"] == allocation["allocation_id"]
            ],
            payment_ids=[
                row["transaction_id"]
                for row in payment_links
                if row["allocation_id"] == allocation["allocation_id"]
            ],
        )
    generation, revision = connection.execute(
        "SELECT dataset_generation,dataset_revision FROM repository_meta WHERE singleton=1"
    ).fetchone()
    return {
        "dataset_generation": generation,
        "dataset_revision": revision,
        "candidates": candidates,
        "evidence": evidence,
        "allocations": allocations,
        "withdrawals": withdrawals,
        "ledger_cash_totals": {key: str(value) for key, value in sorted(cash.items())},
        "payment_ids": [item.payment_id for item in payments],
        "payments": [
            {
                "transaction_id": item.payment_id,
                "occurred_on": item.occurred_on.isoformat(),
                "amount": str(item.amount),
                "currency": item.currency,
                "reserved": item.payment_id in used_payments,
            }
            for item in payments
        ],
        "cash_policy": "canonical_payments_only.v1",
        "window_days": window_days,
    }


def _validate_evidence(
    connection: sqlite3.Connection, item: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> None:
    validate_entity_id(item["evidence_id"])
    _date(item["occurred_on"])
    amount, currency = _value(connection, item["amount_value_id"])
    provenance = connection.execute(
        "SELECT source_occurrence_id FROM record_provenance WHERE provenance_id=?",
        (item["provenance_id"],),
    ).fetchone()
    value_provenance = connection.execute(
        "SELECT provenance_id FROM exact_values WHERE value_id=?",
        (item["amount_value_id"],),
    ).fetchone()
    if (
        provenance is None
        or provenance[0] != item["occurrence_id"]
        or value_provenance[0] != item["provenance_id"]
    ):
        raise ValueError("Broken evidence lineage.")
    _text(item["source_namespace"])
    _text(item["external_key"])
    detail = json.loads(item["detail_json"])
    if not isinstance(detail, dict) or (item["settlement_unit"] and amount.is_zero()):
        raise ValueError("Invalid settlement source meaning.")
    parent_record = evidence.get(item["parent_evidence_id"])
    if parent_record is not None and parent_record["source_namespace"] != item["source_namespace"]:
        raise ValueError("Evidence parent changed namespace.")
    artifact_id = connection.execute(
        "SELECT source_artifact_id FROM source_occurrences WHERE entity_id=?",
        (item["occurrence_id"],),
    ).fetchone()[0]
    lexical = connection.execute(
        "SELECT lexical FROM exact_values WHERE value_id=?", (item["amount_value_id"],)
    ).fetchone()[0]
    preserved = {
        "source_artifact_id": artifact_id,
        "external_key": item["external_key"],
        "evidence_kind": item["evidence_kind"],
        "occurred_on": item["occurred_on"],
        "amount": lexical,
        "currency": currency,
        "settlement_unit": bool(item["settlement_unit"]),
        "detail": detail,
        "parent_external_key": None if parent_record is None else parent_record["external_key"],
        "transaction_id": item["transaction_id"],
    }
    if hashlib.sha256(_json(preserved).encode()).hexdigest() != item["payload_digest"] or item[
        "evidence_id"
    ] != _id(_json([item["source_namespace"], item["external_key"]])):
        raise ValueError("Evidence identity or payload digest changed.")
    seen = {item["evidence_id"]}
    parent = item["parent_evidence_id"]
    while parent is not None:
        if parent in seen or parent not in evidence:
            raise ValueError("Broken evidence hierarchy.")
        seen.add(parent)
        ancestor = evidence[parent]
        if ancestor["evidence_kind"] not in {"purchase", "order"} or (
            item["settlement_unit"] and ancestor["settlement_unit"]
        ):
            raise ValueError("Evidence hierarchy duplicates settlement scope.")
        parent = ancestor["parent_evidence_id"]
    if item["transaction_id"] is not None:
        row = connection.execute(
            "SELECT amount_value_id FROM transactions WHERE entity_id=?",
            (item["transaction_id"],),
        ).fetchone()
        payment, payment_currency = _value(connection, row[0])
        if payment.copy_negate() != amount or payment_currency != currency:
            raise ValueError("Payment evidence disagrees with canonical payment.")


def validate_reconcile(connection: sqlite3.Connection) -> None:
    """Reject broken source lineage, hierarchy, residuals or overlapping active reservations."""
    try:
        evidence = {item["evidence_id"]: item for item in _rows(connection, "reconcile_evidence")}
        for item in evidence.values():
            _validate_evidence(connection, item, evidence)
        withdrawn = {row["allocation_id"] for row in _rows(connection, "reconcile_withdrawals")}
        reserved_evidence: set[str] = set()
        reserved_payments: set[str] = set()
        for allocation in _rows(connection, "reconcile_allocations"):
            identifier = allocation["allocation_id"]
            validate_entity_id(identifier)
            _time(allocation["confirmed_at"])
            eids = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT evidence_id FROM reconcile_allocation_evidence WHERE allocation_id=?",
                    (identifier,),
                )
            )
            pids = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT transaction_id FROM reconcile_allocation_payments "
                    "WHERE allocation_id=?",
                    (identifier,),
                )
            )
            residual, currency = _selection(connection, eids, pids)
            actual, actual_currency = _value(connection, allocation["residual_value_id"])
            if (
                residual != actual
                or currency != actual_currency
                or allocation["status"] != ("matched" if residual.is_zero() else "partial")
            ):
                raise ValueError("Allocation residual is not supported by exact sources.")
            if identifier not in withdrawn:
                if reserved_evidence.intersection(eids) or reserved_payments.intersection(pids):
                    raise ValueError("Overlapping active allocation.")
                reserved_evidence.update(eids)
                reserved_payments.update(pids)
        for withdrawal in _rows(connection, "reconcile_withdrawals"):
            validate_entity_id(withdrawal["withdrawal_id"])
            _time(withdrawal["withdrawn_at"])
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise RepositoryIntegrityError(
            "Canonical reconciliation facts are inconsistent."
        ) from error
