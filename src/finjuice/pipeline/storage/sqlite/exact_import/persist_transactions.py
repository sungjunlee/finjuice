"""Persist exact transaction rows, unresolved accounts, and origin links."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from finjuice.pipeline.ingest.exact_transactions import ExactMappedRow, ExactTransactionMapping
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.exact_import.constants import UNRESOLVED_ACCOUNT_KIND
from finjuice.pipeline.storage.sqlite.exact_import.evidence import (
    IssueView,
    PersistSession,
    SourcePlace,
    add_issues,
    add_row_provenance,
    as_issue,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import RowDecision
from finjuice.pipeline.storage.sqlite.exact_import.overlap import transaction_effective_at
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    ObservationRecord,
    TransactionRecord,
    TransactionSourceLinkRecord,
)

_EMPTY = ""


@dataclass(frozen=True)
class _TxnIds:
    transaction_id: str
    observation_id: str
    provenance_id: str
    account_id: str
    amount_id: str


def persist_transactions(
    session: PersistSession,
    mapping: ExactTransactionMapping,
    decisions: Sequence[RowDecision],
) -> list[str]:
    """Write planned transaction rows and return inserted transaction IDs."""
    inserted: list[str] = []
    by_row = {row.source_row: row for row in mapping.rows}
    for decision in decisions:
        if decision.family != "transactions":
            continue
        row = by_row[decision.source_row]
        transaction_id = _persist_transaction_row(session, mapping, row, decision)
        if transaction_id is not None:
            inserted.append(transaction_id)
    return inserted


def _persist_transaction_row(
    session: PersistSession,
    mapping: ExactTransactionMapping,
    row: ExactMappedRow,
    decision: RowDecision,
) -> str | None:
    extra = _row_payload(mapping, row, decision)
    place = SourcePlace("transaction", row.sheet_name, row.source_row)
    provenance_id = add_row_provenance(session, place, row.cells, extra)
    issues = [as_issue(item) for item in row.issues]
    if decision.action == "quarantine":
        issues.append(
            IssueView(
                "UNRESOLVED_IDENTITY",
                None,
                row.source_row,
                None,
                "Unproven overlapping candidates were not merged.",
            )
        )
    add_issues(session, provenance_id, tuple(issues), sheet_name=row.sheet_name)
    if decision.action == "insert":
        return _insert_supported_transaction(session, row, provenance_id)
    return None


def _insert_supported_transaction(
    session: PersistSession,
    row: ExactMappedRow,
    provenance_id: str,
) -> str:
    assert row.source_amount is not None
    assert row.account_text is not None
    account_id = _add_unresolved_account(session, row.account_text)
    observation_id = _add_row_observation(session, row)
    amount_id = _add_amounts(session, provenance_id, row)
    ids = _TxnIds(new_entity_id(), observation_id, provenance_id, account_id, amount_id)
    session.context.add_transaction(_transaction_record(row, ids))
    session.context.add_transaction_source_link(
        TransactionSourceLinkRecord(
            link_id=new_entity_id(),
            transaction_id=ids.transaction_id,
            provenance_id=ids.provenance_id,
            observation_id=ids.observation_id,
            link_kind="origin",
        )
    )
    return ids.transaction_id


def _add_unresolved_account(session: PersistSession, display_name: str) -> str:
    account_id = new_entity_id()
    session.context.add_account(
        AccountRecord(
            account_id=account_id,
            account_kind=UNRESOLVED_ACCOUNT_KIND,
            display_name=display_name,
            ownership_state="unknown",
        )
    )
    return account_id


def _add_row_observation(session: PersistSession, row: ExactMappedRow) -> str:
    observation_id = new_entity_id()
    session.context.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=session.occurrence_id,
            observed_at=None,
            effective_at=transaction_effective_at(row),
            collected_at=session.collected_at,
            scope_state="partial",
            confirmation_state="unconfirmed",
        )
    )
    return observation_id


def _add_amounts(session: PersistSession, provenance_id: str, row: ExactMappedRow) -> str:
    source = row.source_amount
    assert source is not None
    source_id = new_entity_id()
    session.context.add_exact_value(source_id, source, provenance_id=provenance_id)
    interpreted = row.interpreted_amount
    if interpreted is None:
        return source_id
    interpreted_id = new_entity_id()
    session.context.add_exact_value(interpreted_id, interpreted, provenance_id=provenance_id)
    return interpreted_id


def _transaction_record(row: ExactMappedRow, ids: _TxnIds) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=ids.transaction_id,
        observation_id=ids.observation_id,
        provenance_id=ids.provenance_id,
        account_id=ids.account_id,
        amount_value_id=ids.amount_id,
        date_raw=_raw(row.date_raw),
        time_raw=_raw(row.time_raw),
        datetime_raw=_raw(row.datetime_raw),
        type_raw=row.type_raw,
        type_norm=row.type_norm,
        account_text=row.account_text or _EMPTY,
        major_raw=row.major_raw,
        minor_raw=row.minor_raw,
        merchant_raw=row.merchant_raw,
        memo_raw=row.memo_raw,
        timezone_state=row.temporal.timezone_state,
    )


def _row_payload(
    mapping: ExactTransactionMapping,
    row: ExactMappedRow,
    decision: RowDecision,
) -> dict[str, object]:
    source = _value_view(row.source_amount)
    interpreted = _value_view(row.interpreted_amount)
    return {
        "action": decision.action,
        "candidate_ids": list(decision.candidate_ids),
        "date1904": mapping.date1904,
        "interpreted_amount": interpreted,
        "source_amount": source,
        "supported": row.supported,
        "temporal_policy": row.temporal.temporal_policy,
        "timezone_state": row.temporal.timezone_state,
    }


def _value_view(value: ExactValue | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "coefficient": value.coefficient,
        "currency": value.currency,
        "currency_unknown": value.currency_unknown,
        "lexical": value.lexical,
        "origin_kind": value.origin_kind,
        "scale": value.scale,
        "unit": value.unit,
        "value_kind": value.value_kind,
    }


def _raw(value: str | None) -> str:
    return _EMPTY if value is None else value
