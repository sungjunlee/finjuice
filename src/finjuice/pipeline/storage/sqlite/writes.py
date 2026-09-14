"""Shared typed-row inserts for the authoritative SQLite schema.

This module is internal storage plumbing. :class:`TypedRowWriter` owns only the SQL for
typed preservation rows so that ``RepositoryBuilder`` and ``MutationContext`` can stop
duplicating it. It deliberately does **not** own anything semantic:

* The caller owns the connection lifecycle and the authoritative transaction. Every add
  requires an already active transaction and never issues ``BEGIN``, ``COMMIT``, or
  ``ROLLBACK`` on the caller's transaction.
* The caller owns audit entries, changeset receipts, authority checks, and revision
  increments. ``MutationContext`` wrappers record their audit delta after a successful add.
* Each add is atomic through its own uniquely named ``SAVEPOINT``: on failure the partial
  rows are rolled back and the caller's transaction and any caller savepoints stay valid.

No account lookup, merging, numeric normalization, or financial logging happens here.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Final, TypeVar, cast

from finjuice.pipeline.storage.sqlite.errors import SQLiteStorageError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import (
    canonical_locator,
    new_entity_id,
    validate_entity_id,
)
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    AssetSnapshotRecord,
    EntityKind,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
    PartyRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    ResourceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
)

__all__ = ["TypedRowWriter", "TypedWriteError"]

_EXACT_SUBTYPE_INSERT_SQL: Final = {
    "quantity": "INSERT INTO quantity_values (value_id, unit) VALUES (?, ?)",
    "rate": "INSERT INTO rate_values (value_id, unit) VALUES (?, ?)",
    "number": "INSERT INTO number_values (value_id, unit) VALUES (?, ?)",
}

_Method = TypeVar("_Method", bound=Callable[..., Any])


class TypedWriteError(SQLiteStorageError):
    """A typed write was attempted outside an active caller transaction."""


def _atomic_add(method: _Method) -> _Method:
    """Wrap one typed add in a rollback-on-error savepoint inside the caller transaction."""

    @wraps(method)
    def wrapped(self: TypedRowWriter, *args: Any, **kwargs: Any) -> Any:
        with self._savepoint():
            return method(self, *args, **kwargs)

    return cast(_Method, wrapped)


class TypedRowWriter:
    """Insert typed preservation rows into an already open, already transacting connection.

    The writer never opens, closes, commits, or rolls back the connection. It only creates and
    releases its own savepoints, so a failed add leaves the caller exactly where it was.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._savepoint_serial = 0

    @_atomic_add
    def add_source_occurrence(self, record: SourceOccurrenceRecord) -> None:
        """Add a distinct source occurrence, even when source bytes are reused."""
        self._insert_entity(record.occurrence_id, "source_occurrence")
        self._connection.execute(
            "INSERT INTO source_occurrences "
            "(entity_id, source_artifact_id, occurrence_kind, original_filename, imported_at, "
            "parser_version, source_schema_version, legacy_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.occurrence_id,
                record.artifact_id,
                record.occurrence_kind,
                record.original_filename,
                record.imported_at,
                record.parser_version,
                record.source_schema_version,
                record.legacy_path,
            ),
        )

    @_atomic_add
    def add_provenance(self, record: ProvenanceRecord) -> None:
        """Add canonical source coordinates and a non-collapsing legacy locator."""
        validate_entity_id(record.provenance_id)
        validate_entity_id(record.occurrence_id)
        self._connection.execute(
            "INSERT INTO record_provenance "
            "(provenance_id, source_occurrence_id, source_coordinate_json, "
            "legacy_locator_json, parser_version, source_schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.provenance_id,
                record.occurrence_id,
                _canonical_json(record.source_coordinate),
                canonical_locator(record.legacy_locator),
                record.parser_version,
                record.source_schema_version,
            ),
        )

    @_atomic_add
    def add_exact_value(
        self,
        value_id: str,
        value: ExactValue,
        *,
        provenance_id: str | None = None,
    ) -> None:
        """Add a canonical exact value and its required semantic subtype."""
        validate_entity_id(value_id)
        if provenance_id is not None:
            validate_entity_id(provenance_id)
        self._connection.execute(
            "INSERT INTO exact_values "
            "(value_id, value_kind, coefficient, scale, lexical, origin_kind, provenance_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                value_id,
                value.value_kind,
                value.coefficient,
                value.scale,
                value.lexical,
                value.origin_kind,
                provenance_id,
            ),
        )
        if value.value_kind == "money":
            self._connection.execute(
                "INSERT INTO money_values (value_id, currency_code, currency_unknown) "
                "VALUES (?, ?, ?)",
                (value_id, value.currency, int(value.currency_unknown)),
            )
        else:
            self._connection.execute(
                _EXACT_SUBTYPE_INSERT_SQL[value.value_kind],
                (value_id, value.unit),
            )

    @_atomic_add
    def add_party(self, record: PartyRecord) -> None:
        """Add a party foundation row."""
        self._insert_entity(record.party_id, "party")
        self._connection.execute(
            "INSERT INTO parties (entity_id, party_kind, display_name) VALUES (?, ?, ?)",
            (record.party_id, record.party_kind, record.display_name),
        )

    @_atomic_add
    def add_account(self, record: AccountRecord) -> None:
        """Add an account with explicit ownership state; no lookup or merge is attempted."""
        self._insert_entity(record.account_id, "account")
        self._connection.execute(
            "INSERT INTO accounts "
            "(entity_id, account_kind, display_name, ownership_state, owner_party_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.account_id,
                record.account_kind,
                record.display_name,
                record.ownership_state,
                record.owner_party_id,
            ),
        )

    @_atomic_add
    def add_resource(self, record: ResourceRecord) -> None:
        """Add a resource or instrument foundation row."""
        self._insert_entity(record.resource_id, "resource")
        self._connection.execute(
            "INSERT INTO resources (entity_id, resource_kind, display_name) VALUES (?, ?, ?)",
            (record.resource_id, record.resource_kind, record.display_name),
        )

    @_atomic_add
    def add_observation(self, record: ObservationRecord) -> None:
        """Add source-backed temporal and scope context."""
        self._insert_entity(record.observation_id, "observation")
        self._connection.execute(
            "INSERT INTO observations "
            "(entity_id, source_occurrence_id, observed_at, effective_at, collected_at, "
            "scope_state, confirmation_state, supersedes_observation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.occurrence_id,
                record.observed_at,
                record.effective_at,
                record.collected_at,
                record.scope_state,
                record.confirmation_state,
                record.supersedes_observation_id,
            ),
        )

    @_atomic_add
    def add_transaction(self, record: TransactionRecord) -> None:
        """Add a typed transaction without collapsing equal row hashes."""
        self._insert_entity(record.transaction_id, "transaction")
        self._connection.execute(
            "INSERT INTO transactions "
            "(entity_id, observation_id, provenance_id, account_id, amount_value_id, date_raw, "
            "time_raw, datetime_raw, timezone_state, type_raw, type_norm, major_raw, minor_raw, "
            "merchant_raw, memo_raw, notes_manual, account_text, counterparty, category_rule, "
            "category_manual, category_final, tags_rule_json, tags_ai_json, tags_manual_json, "
            "tags_final_json, confidence_value_id, needs_review, is_transfer_candidate, "
            "is_transfer, transfer_group_id) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?)",
            _transaction_parameters(record),
        )

    @_atomic_add
    def add_overview_fact(self, record: OverviewFactRecord) -> None:
        """Add one typed overview fact."""
        self._insert_entity(record.fact_id, "overview_fact")
        self._connection.execute(
            "INSERT INTO overview_facts "
            "(entity_id, observation_id, provenance_id, snapshot_date, sheet_name, block_id, "
            "block_title, fact_kind, row_label, column_label, numeric_value_id, value_text, "
            "value_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.fact_id,
                record.observation_id,
                record.provenance_id,
                record.snapshot_date,
                record.sheet_name,
                record.block_id,
                record.block_title,
                record.fact_kind,
                record.row_label,
                record.column_label,
                record.numeric_value_id,
                record.value_text,
                record.value_type,
            ),
        )

    @_atomic_add
    def add_overview_balance(self, record: OverviewBalanceRecord) -> None:
        """Add a typed overview balance."""
        self._insert_entity(record.balance_id, "overview_balance")
        self._connection.execute(
            "INSERT INTO overview_balances "
            "(entity_id, observation_id, provenance_id, source_fact_id, amount_value_id, "
            "snapshot_date, side, category, item_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.balance_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.amount_value_id,
                record.snapshot_date,
                record.side,
                record.category,
                record.item_name,
            ),
        )

    @_atomic_add
    def add_overview_cashflow(self, record: OverviewCashflowRecord) -> None:
        """Add a typed overview cashflow."""
        self._insert_entity(record.cashflow_id, "overview_cashflow")
        self._connection.execute(
            "INSERT INTO overview_cashflows "
            "(entity_id, observation_id, provenance_id, source_fact_id, amount_value_id, "
            "snapshot_date, period_month, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.cashflow_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.amount_value_id,
                record.snapshot_date,
                record.period_month,
                record.category,
            ),
        )

    @_atomic_add
    def add_overview_insurance(self, record: OverviewInsuranceRecord) -> None:
        """Add a typed overview insurance row."""
        self._insert_entity(record.insurance_id, "overview_insurance")
        self._connection.execute(
            "INSERT INTO overview_insurance "
            "(entity_id, observation_id, provenance_id, source_fact_id, paid_amount_value_id, "
            "snapshot_date, institution, policy_name, contract_status, contract_date, "
            "maturity_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.insurance_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.paid_amount_value_id,
                record.snapshot_date,
                record.institution,
                record.policy_name,
                record.contract_status,
                record.contract_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_overview_investment(self, record: OverviewInvestmentRecord) -> None:
        """Add a typed overview investment row."""
        self._insert_entity(record.investment_id, "overview_investment")
        self._connection.execute(
            "INSERT INTO overview_investments "
            "(entity_id, observation_id, provenance_id, source_fact_id, principal_value_id, "
            "valuation_value_id, return_rate_value_id, snapshot_date, product_type, institution, "
            "product_name, start_date, maturity_date) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.investment_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.principal_value_id,
                record.valuation_value_id,
                record.return_rate_value_id,
                record.snapshot_date,
                record.product_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_overview_loan(self, record: OverviewLoanRecord) -> None:
        """Add a typed overview loan row."""
        self._insert_entity(record.loan_id, "overview_loan")
        self._connection.execute(
            "INSERT INTO overview_loans "
            "(entity_id, observation_id, provenance_id, source_fact_id, principal_value_id, "
            "balance_value_id, interest_rate_value_id, snapshot_date, loan_type, institution, "
            "product_name, start_date, maturity_date) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.loan_id,
                record.observation_id,
                record.provenance_id,
                record.source_fact_id,
                record.principal_value_id,
                record.balance_value_id,
                record.interest_rate_value_id,
                record.snapshot_date,
                record.loan_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
            ),
        )

    @_atomic_add
    def add_asset_snapshot(self, record: AssetSnapshotRecord) -> None:
        """Add a typed asset position snapshot."""
        self._insert_entity(record.snapshot_id, "asset_snapshot")
        self._connection.execute(
            "INSERT INTO asset_snapshots "
            "(entity_id, observation_id, provenance_id, account_id, resource_id, "
            "quantity_value_id, market_value_id, snapshot_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.snapshot_id,
                record.observation_id,
                record.provenance_id,
                record.account_id,
                record.resource_id,
                record.quantity_value_id,
                record.market_value_id,
                record.snapshot_date,
            ),
        )

    @_atomic_add
    def add_legacy_payload(
        self,
        provenance_id: str,
        payload: Mapping[str, Any] | Sequence[Any],
        *,
        payload_id: str | None = None,
    ) -> str:
        """Preserve the full legacy payload alongside typed rows and return its ID."""
        payload_id = payload_id or new_entity_id()
        validate_entity_id(payload_id)
        validate_entity_id(provenance_id)
        self._connection.execute(
            "INSERT INTO legacy_payloads "
            "(payload_id, provenance_id, payload_json) VALUES (?, ?, ?)",
            (payload_id, provenance_id, _canonical_json(payload)),
        )
        return payload_id

    @_atomic_add
    def add_preservation_issue(self, record: PreservationIssueRecord) -> str:
        """Record a lossless typing or preservation problem and return its issue ID."""
        issue_id = record.issue_id or new_entity_id()
        validate_entity_id(issue_id)
        validate_entity_id(record.provenance_id)
        self._connection.execute(
            "INSERT INTO preservation_issues "
            "(issue_id, provenance_id, field_name, issue_kind, lexical_value, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                issue_id,
                record.provenance_id,
                record.field_name,
                record.issue_kind,
                record.lexical_value,
                _canonical_json(record.detail),
            ),
        )
        return issue_id

    @contextmanager
    def _savepoint(self) -> Iterator[None]:
        """Guard one add with a private, uniquely named savepoint inside the caller transaction."""
        if not self._connection.in_transaction:
            raise TypedWriteError("Typed writes require an active caller transaction.")
        self._savepoint_serial += 1
        name = f"typed_write_{self._savepoint_serial}"
        self._connection.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self._connection.execute(f"ROLLBACK TO {name}")
            self._connection.execute(f"RELEASE {name}")
            raise
        else:
            self._connection.execute(f"RELEASE {name}")

    def _insert_entity(self, entity_id: str, entity_kind: EntityKind) -> None:
        validate_entity_id(entity_id)
        self._connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, ?)",
            (entity_id, entity_kind),
        )


def _transaction_parameters(record: TransactionRecord) -> tuple[Any, ...]:
    return (
        record.transaction_id,
        record.observation_id,
        record.provenance_id,
        record.account_id,
        record.amount_value_id,
        record.date_raw,
        record.time_raw,
        record.datetime_raw,
        record.timezone_state,
        record.type_raw,
        record.type_norm,
        record.major_raw,
        record.minor_raw,
        record.merchant_raw,
        record.memo_raw,
        record.notes_manual,
        record.account_text,
        record.counterparty,
        record.category_rule,
        record.category_manual,
        record.category_final,
        _canonical_array_text(record.tags_rule_json),
        _canonical_array_text(record.tags_ai_json),
        _canonical_array_text(record.tags_manual_json),
        _canonical_array_text(record.tags_final_json),
        record.confidence_value_id,
        _optional_bool(record.needs_review),
        _optional_bool(record.is_transfer_candidate),
        _optional_bool(record.is_transfer),
        record.transfer_group_id,
    )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Preserved JSON values must have a canonical finite encoding.") from exc


def _canonical_array_text(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Transaction tag fields must contain JSON arrays.") from exc
    if not isinstance(parsed, list):
        raise ValueError("Transaction tag fields must contain JSON arrays.")
    return _canonical_json(parsed)


def _optional_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("Optional flags must be booleans or null.")
    return int(value)
