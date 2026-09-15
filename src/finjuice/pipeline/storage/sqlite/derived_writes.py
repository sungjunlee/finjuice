"""Derived-state write helpers for the authoritative mutation boundary.

Owns bulk transaction snapshots, preserved-tag decoding, manual-edit views, and
the parameterized derived-column UPDATE builder. Public names stay importable
from :mod:`finjuice.pipeline.storage.sqlite.mutations`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, TypeAlias

from finjuice.pipeline.storage.sqlite.errors import (
    MutationValidationError,
    RepositoryIntegrityError,
)
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

JSONValue: TypeAlias = Any
_DERIVED_COLUMNS: Final[dict[str, str]] = {
    "category_final": "category_final",
    "category_rule": "category_rule",
    "confidence_value_id": "confidence_value_id",
    "is_transfer": "is_transfer",
    "is_transfer_candidate": "is_transfer_candidate",
    "needs_review": "needs_review",
    "tags_final": "tags_final_json",
    "tags_rule": "tags_rule_json",
    "transfer_group_id": "transfer_group_id",
}
_JSON_DERIVED_KEYS = frozenset({"tags_final", "tags_rule"})
_BOOL_DERIVED_KEYS = frozenset({"is_transfer", "is_transfer_candidate", "needs_review"})
_MIGRATED_TRANSACTION_SOURCE_SQL = (
    "SELECT txn.entity_id FROM transactions AS txn "
    "JOIN migration_identities AS identity ON identity.entity_id = txn.entity_id "
    "AND identity.record_kind = 'transaction' "
    "JOIN legacy_payloads AS payload ON payload.provenance_id = txn.provenance_id "
    "JOIN record_provenance AS provenance ON provenance.provenance_id = txn.provenance_id "
    "JOIN observations AS observation ON observation.entity_id = txn.observation_id "
    "AND observation.source_occurrence_id = provenance.source_occurrence_id "
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


_BULK_TRANSACTION_SQL = (
    "SELECT txn.entity_id, txn.date_raw, txn.time_raw, txn.datetime_raw, txn.timezone_state, "
    "txn.type_raw, txn.type_norm, txn.major_raw, txn.minor_raw, txn.merchant_raw, "
    "txn.memo_raw, txn.notes_manual, txn.account_text, txn.counterparty, txn.category_rule, "
    "txn.category_manual, txn.category_final, txn.tags_rule_json, txn.tags_ai_json, "
    "txn.tags_manual_json, txn.tags_final_json, txn.confidence_value_id, txn.needs_review, "
    "txn.is_transfer_candidate, txn.is_transfer, txn.transfer_group_id, txn.provenance_id, "
    "txn.observation_id, txn.account_id, txn.amount_value_id, amount.coefficient, "
    "amount.scale, amount.lexical, amount.value_kind, amount.origin_kind, "
    "money.currency_code, money.currency_unknown, confidence.coefficient, confidence.scale, "
    "observation.observed_at, observation.effective_at, observation.collected_at, "
    "confidence_number.unit "
    "FROM transactions AS txn "
    "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id "
    "JOIN money_values AS money ON money.value_id = txn.amount_value_id "
    "LEFT JOIN exact_values AS confidence ON confidence.value_id = txn.confidence_value_id "
    "LEFT JOIN number_values AS confidence_number "
    "ON confidence_number.value_id = txn.confidence_value_id "
    "JOIN observations AS observation ON observation.entity_id = txn.observation_id"
)


def _canonical_write_json(value: JSONValue) -> str:
    """Encode one derived-write payload with the mutation JSON contract."""
    from finjuice.pipeline.storage.sqlite.mutations import _canonical_request_json

    return _canonical_request_json(value)


def _has_migrated_transaction_source(connection: sqlite3.Connection, transaction_id: str) -> bool:
    """Recognize captured legacy rows whose tag spelling and duplicates were preserved."""
    return (
        connection.execute(
            _MIGRATED_TRANSACTION_SOURCE_SQL + "WHERE txn.entity_id = ?", (transaction_id,)
        ).fetchone()
        is not None
    )


def _parse_preserved_string_array(value: Any) -> list[str]:
    """Decode source-backed legacy arrays without silently normalizing their members."""
    if value is None:
        return []
    try:
        parsed = json.loads(str(value), parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored transaction tags are invalid JSON.") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise RepositoryIntegrityError("Stored legacy transaction tags are not a string array.")
    return parsed


def _parse_string_array(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(str(value), parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored transaction tags are invalid JSON.") from exc
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(parsed) != len(set(parsed))
    ):
        raise RepositoryIntegrityError("Stored transaction tags are not a canonical string array.")
    return parsed


def _manual_transaction_view(current: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Return stable read fields shared by inspection, write, and replay receipts."""
    return {
        "date": current["date_raw"],
        "time": current["time_raw"],
        "datetime": current["datetime_raw"],
        "type_raw": current["type_raw"],
        "type_norm": current["type_norm"],
        "major_raw": current["major_raw"],
        "minor_raw": current["minor_raw"],
        "merchant_raw": current["merchant_raw"],
        "memo_raw": current["memo_raw"],
        "account": current["account_text"],
        "counterparty": current["counterparty"],
        "category_rule": current["category_rule"],
        "tags_rule": current["tags_rule"],
        "tags_ai": current["tags_ai"],
        "amount_exact": current["amount_exact"],
        "currency": current["currency"],
        "is_transfer_candidate": current["is_transfer_candidate"],
        "is_transfer": current["is_transfer"],
        "transfer_group_id": current["transfer_group_id"],
    }


def _manual_audit_state(current: Mapping[str, Any]) -> dict[str, JSONValue]:
    return {
        "category_final": current["category_final"],
        "category_manual": current["category_manual"],
        "confidence_exact": current["confidence_exact"],
        "needs_review": current["needs_review"],
        "notes_manual": current["notes_manual"],
        "tags_final": current["tags_final_audit"],
        "tags_manual": current["tags_manual_audit"],
    }


def _resolve_manual_category(
    category_manual: Any,
    category_rule: Any,
    minor_raw: Any,
    major_raw: Any,
) -> str:
    for candidate in (category_manual, category_rule, minor_raw, major_raw):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return "미분류"


def _exact_equals_integer(
    coefficient: str | None,
    scale: int | None,
    expected: int,
) -> bool:
    if coefficient is None or scale is None:
        return False
    coefficient_value = int(str(coefficient))
    scale_value = int(scale)
    return bool(coefficient_value == expected * 10**scale_value)


def _exact_decimal_text(coefficient: str | None, scale: int | None) -> str | None:
    if coefficient is None or scale is None:
        return None
    negative = coefficient.startswith("-")
    digits = coefficient.removeprefix("-")
    if scale == 0:
        rendered = digits
    elif len(digits) > scale:
        rendered = f"{digits[:-scale]}.{digits[-scale:]}"
    else:
        rendered = f"0.{('0' * (scale - len(digits)))}{digits}"
    return f"-{rendered}" if negative and digits != "0" else rendered


def _require_coverage_target(target: int) -> None:
    if target not in (0, 1):
        raise MutationValidationError("Coverage confidence must be 0 or 1.")


def _load_bulk_transaction_rows(
    connection: sqlite3.Connection,
    transaction_ids: Sequence[str] | None,
) -> tuple[dict[str, Any], ...]:
    sql, parameters = _bulk_transaction_query(transaction_ids)
    rows = connection.execute(sql, parameters).fetchall()
    if transaction_ids is not None and len(rows) != len(set(transaction_ids)):
        raise MutationValidationError("Transaction identifier was not found.")
    migrated = {row[0] for row in connection.execute(_MIGRATED_TRANSACTION_SOURCE_SQL)}
    return tuple(_bulk_transaction_mapping(row, preserved=row[0] in migrated) for row in rows)


def _bulk_transaction_query(
    transaction_ids: Sequence[str] | None,
) -> tuple[str, tuple[Any, ...]]:
    if transaction_ids is None:
        return f"{_BULK_TRANSACTION_SQL} ORDER BY txn.entity_id", ()
    identifiers = tuple(transaction_ids)
    seen: set[str] = set()
    for transaction_id in identifiers:
        validate_entity_id(transaction_id)
        if transaction_id in seen:
            raise MutationValidationError("Transaction identifiers must be unique.")
        seen.add(transaction_id)
    if not identifiers:
        return f"{_BULK_TRANSACTION_SQL} WHERE 0 ORDER BY txn.entity_id", ()
    placeholders = ", ".join("?" for _ in identifiers)
    sql = f"{_BULK_TRANSACTION_SQL} WHERE txn.entity_id IN ({placeholders}) ORDER BY txn.entity_id"
    return sql, identifiers


def _bulk_transaction_mapping(row: Sequence[Any], *, preserved: bool = False) -> dict[str, Any]:
    coefficient = None if row[37] is None else str(row[37])
    scale = None if row[38] is None else int(row[38])
    amount_coefficient = str(row[30])
    amount_scale = int(row[31])
    mapping = _bulk_transaction_core(row, preserved=preserved)
    mapping.update(_bulk_transaction_amount(row, amount_coefficient, amount_scale))
    mapping.update(
        {
            "confidence_coefficient": coefficient,
            "confidence_exact": _exact_decimal_text(coefficient, scale),
            "confidence_scale": scale,
            "confidence_unit": None if row[42] is None else str(row[42]),
            "collected_at": row[41],
            "effective_at": row[40],
            "observed_at": row[39],
        }
    )
    return mapping


def _bulk_transaction_core(row: Sequence[Any], *, preserved: bool = False) -> dict[str, Any]:
    mapping = _bulk_transaction_identity(row)
    mapping.update(_bulk_transaction_classification(row, preserved=preserved))
    return mapping


def _bulk_transaction_identity(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "account_id": row[28],
        "account_text": row[12],
        "counterparty": row[13],
        "date_raw": row[1],
        "datetime_raw": row[3],
        "observation_id": row[27],
        "provenance_id": row[26],
        "time_raw": row[2],
        "timezone_state": row[4],
        "transaction_id": str(row[0]),
        "type_norm": row[6],
        "type_raw": row[5],
    }


def _bulk_transaction_classification(
    row: Sequence[Any], *, preserved: bool = False
) -> dict[str, Any]:
    parse_tags = _parse_preserved_string_array if preserved else _parse_string_array
    return {
        "category_final": row[16],
        "category_manual": row[15],
        "category_rule": row[14],
        "confidence_value_id": row[21],
        "is_transfer": None if row[24] is None else bool(row[24]),
        "is_transfer_candidate": None if row[23] is None else bool(row[23]),
        "major_raw": row[7],
        "memo_raw": row[10],
        "merchant_raw": row[9],
        "minor_raw": row[8],
        "needs_review": None if row[22] is None else bool(row[22]),
        "notes_manual": row[11],
        "tags_ai": parse_tags(row[18]),
        "tags_final": parse_tags(row[20]),
        "tags_manual": parse_tags(row[19]),
        "tags_rule": parse_tags(row[17]),
        "transfer_group_id": row[25],
    }


def _bulk_transaction_amount(
    row: Sequence[Any],
    amount_coefficient: str,
    amount_scale: int,
) -> dict[str, Any]:
    return {
        "amount_coefficient": amount_coefficient,
        "amount_exact": _exact_decimal_text(amount_coefficient, amount_scale),
        "amount_lexical": None if row[32] is None else str(row[32]),
        "amount_origin_kind": str(row[34]),
        "amount_scale": amount_scale,
        "amount_value_id": row[29],
        "amount_value_kind": str(row[33]),
        "currency": None if row[35] is None else str(row[35]),
        "currency_unknown": bool(row[36]),
    }


def _load_stored_derived_state(
    connection: sqlite3.Connection,
    transaction_id: str,
) -> dict[str, JSONValue]:
    """Load the actual derived columns used for no-op, audit, and stale-before checks."""
    row = connection.execute(
        "SELECT category_final, category_rule, confidence_value_id, needs_review, "
        "tags_final_json, tags_rule_json, is_transfer, is_transfer_candidate, "
        "transfer_group_id FROM transactions WHERE entity_id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None:
        raise MutationValidationError("Transaction identifier was not found.")
    return _stored_derived_mapping(
        row, preserved=_has_migrated_transaction_source(connection, transaction_id)
    )


def _stored_derived_mapping(row: Sequence[Any], *, preserved: bool = False) -> dict[str, JSONValue]:
    parse_tags = _parse_preserved_string_array if preserved else _parse_string_array
    return {
        "category_final": row[0],
        "category_rule": row[1],
        "confidence_value_id": row[2],
        "is_transfer": None if row[6] is None else bool(row[6]),
        "is_transfer_candidate": None if row[7] is None else bool(row[7]),
        "needs_review": None if row[3] is None else bool(row[3]),
        "tags_final": parse_tags(row[4]),
        "tags_rule": parse_tags(row[5]),
        "transfer_group_id": row[8],
    }


def _reject_stale_derived_before(
    before: Mapping[str, JSONValue],
    stored: Mapping[str, JSONValue],
    after: Mapping[str, JSONValue],
) -> None:
    """Reject caller before-state that does not match the row currently stored."""
    if not isinstance(before, Mapping):
        raise MutationValidationError("Derived before-state is missing a field.")
    for key in after:
        if key not in _DERIVED_COLUMNS:
            raise MutationValidationError("Unsupported derived field.")
        if key not in before:
            raise MutationValidationError("Derived before-state is missing a field.")
    for key, claimed in before.items():
        _reject_mismatched_derived_field(key, claimed, stored)


def _reject_mismatched_derived_field(
    key: str,
    claimed: JSONValue,
    stored: Mapping[str, JSONValue],
) -> None:
    if key not in _DERIVED_COLUMNS:
        raise MutationValidationError("Unsupported derived field.")
    # Before-state is evidence, not a proposed canonical write. The stored tags
    # have already passed the native or source-backed preservation parser.
    if key not in _JSON_DERIVED_KEYS:
        _derived_sql_value(key, claimed)
    actual = _derived_audit_value(key, stored[key])
    if _derived_audit_value(key, claimed) != actual:
        raise MutationValidationError("Derived before-state does not match stored state.")


def _derived_update_parts(
    after: Mapping[str, JSONValue],
    before: Mapping[str, JSONValue],
) -> tuple[list[str], list[Any], dict[str, JSONValue], dict[str, JSONValue]]:
    if not after:
        raise MutationValidationError("Derived state update must include at least one field.")
    unknown = [key for key in after if key not in _DERIVED_COLUMNS]
    if unknown:
        raise MutationValidationError("Unsupported derived field.")
    write = _DerivedWrite()
    for key, value in after.items():
        _append_derived_assignment(write, key, value, before)
    if not write.assignments:
        return [], [], {}, {}
    _canonical_write_json(write.audit_before)
    _canonical_write_json(write.audit_after)
    return write.assignments, write.parameters, write.audit_before, write.audit_after


@dataclass
class _DerivedWrite:
    assignments: list[str] = field(default_factory=list)
    parameters: list[Any] = field(default_factory=list)
    audit_before: dict[str, JSONValue] = field(default_factory=dict)
    audit_after: dict[str, JSONValue] = field(default_factory=dict)


def _append_derived_assignment(
    write: _DerivedWrite,
    key: str,
    value: JSONValue,
    before: Mapping[str, JSONValue],
) -> None:
    if key not in before:
        raise MutationValidationError("Derived before-state is missing a field.")
    sql_value = _derived_sql_value(key, value)
    audit_value = _derived_audit_value(key, value)
    before_value = _derived_audit_value(key, before[key])
    if audit_value == before_value:
        return
    write.assignments.append(f"{_DERIVED_COLUMNS[key]} = ?")
    write.parameters.append(sql_value)
    write.audit_before[key] = before_value
    write.audit_after[key] = audit_value


def _derived_sql_value(key: str, value: JSONValue) -> JSONValue:
    if key in _JSON_DERIVED_KEYS:
        return _derived_tags_sql(value)
    if key in _BOOL_DERIVED_KEYS:
        return _derived_flag_sql(value)
    if key == "confidence_value_id":
        return _derived_confidence_sql(value)
    if value is not None and not isinstance(value, str):
        raise MutationValidationError("Derived text fields must be strings or null.")
    return value


def _derived_tags_sql(value: JSONValue) -> str:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MutationValidationError("Derived tags must be a canonical string array.")
    return _canonical_write_json(value)


def _derived_flag_sql(value: JSONValue) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise MutationValidationError("Derived flags must be boolean or null.")
    return int(value)


def _derived_confidence_sql(value: JSONValue) -> str | None:
    if value is None:
        return None
    validate_entity_id(str(value))
    return str(value)


def _derived_audit_value(key: str, value: JSONValue) -> JSONValue:
    if key in _JSON_DERIVED_KEYS:
        if isinstance(value, list):
            return list(value)
        return _parse_string_array(value)
    if key in _BOOL_DERIVED_KEYS:
        return None if value is None else bool(value)
    return value
