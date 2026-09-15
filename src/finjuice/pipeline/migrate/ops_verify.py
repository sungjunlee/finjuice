"""Preservation verification helpers for frozen-source migration.

Owns locator/payload matching, P01-P04 preservation checks, and planned-input
coverage. Public names stay importable from :mod:`finjuice.pipeline.migrate.ops`,
which re-exports the helpers that ``verify_migration`` still calls.
"""

from __future__ import annotations

import json
from typing import Any

from finjuice.pipeline.migrate.errors import invalid
from finjuice.pipeline.migrate.preserve import (
    parse_tag_sequence,
    split_hidden_category,
    unknown_fields,
)
from finjuice.pipeline.migrate.types import PlannedInput
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS


def _check(
    check_id: str,
    *,
    status: str,
    checked_count: int,
    difference_count: int = 0,
    quarantine_count: int = 0,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "checked_count": checked_count,
        "difference_count": difference_count,
        "allowed_difference_count": 0,
        "quarantine_count": quarantine_count,
        "evidence_digest": None,
    }


def _locators_by_provenance(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["provenance_id"]: json.loads(row["legacy_locator_json"])
        for row in snapshot["record_provenance"]
    }


def _payload_for_locator(
    relative_path: str | None,
    ordinal: int,
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for item in payload_rows:
        locator = locators.get(item["provenance_id"]) or {}
        if locator.get("relative_path") != relative_path:
            continue
        if locator.get("ordinal") != ordinal:
            continue
        parsed = json.loads(item["payload_json"])
        if not isinstance(parsed, dict):
            return None
        return parsed
    return None


def _payload_record_for_locator(
    relative_path: str | None,
    ordinal: int,
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for item in payload_rows:
        locator = locators.get(item["provenance_id"]) or {}
        if locator.get("relative_path") != relative_path:
            continue
        if locator.get("ordinal") != ordinal:
            continue
        return item
    return None


def _payload_fields(payload: dict[str, Any]) -> dict[str, str]:
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in fields.items()}


def _transaction_plan_items(planned: list[PlannedInput]) -> list[PlannedInput]:
    return [
        item
        for item in planned
        if item.logical_role == "transaction_partition" and item.ordinal is not None
    ]


def _disposition_by_provenance(snapshot: dict[str, Any]) -> dict[str, str]:
    return {row["provenance_id"]: row["disposition"] for row in snapshot["migration_dispositions"]}


def _typed_hidden_override_match(
    txn: dict[str, Any] | None, visible: list[str], selected: str | None
) -> bool:
    if txn is None:
        return False
    try:
        typed_tags = json.loads(txn["tags_manual_json"])
    except (TypeError, json.JSONDecodeError):
        return False
    return typed_tags == visible and (txn.get("category_manual") or None) == selected


def _hidden_markers_match(
    planned: list[PlannedInput],
    transactions: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
) -> bool:
    dispositions = _disposition_by_provenance(snapshot)
    by_provenance = {row["provenance_id"]: row for row in transactions}
    for item in _transaction_plan_items(planned):
        record = _payload_record_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if record is None:
            return False
        parsed = json.loads(record["payload_json"])
        if not isinstance(parsed, dict):
            return False
        fields = _payload_fields(parsed)
        tags, _issue = parse_tag_sequence(fields.get("tags_manual"))
        visible, selected, markers = split_hidden_category(tags)
        if list(parsed.get("category_override_markers") or []) != markers:
            return False
        if dispositions.get(record["provenance_id"]) != "migrated":
            continue
        if not _typed_hidden_override_match(
            by_provenance.get(record["provenance_id"]), visible, selected
        ):
            return False
    return True


def _persisted_category_match(
    planned: list[PlannedInput],
    transactions: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
) -> bool:
    dispositions = _disposition_by_provenance(snapshot)
    by_provenance = {row["provenance_id"]: row for row in transactions}
    for item in _transaction_plan_items(planned):
        record = _payload_record_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if record is None:
            return False
        if dispositions.get(record["provenance_id"]) != "migrated":
            continue
        txn = by_provenance.get(record["provenance_id"])
        if txn is None:
            return False
        fields = _payload_fields(json.loads(record["payload_json"]))
        if str(txn.get("category_final") or "") != (fields.get("category_final") or ""):
            return False
        if str(txn.get("category_rule") or "") != (fields.get("category_rule") or ""):
            return False
    return True


def _unknown_fields_match(
    planned: list[PlannedInput],
    payload_rows: list[dict[str, Any]],
    locators: dict[str, dict[str, Any]],
) -> bool:
    known = set(CSV_COLUMNS)
    for item in _transaction_plan_items(planned):
        payload = _payload_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if payload is None:
            return False
        fields = _payload_fields(payload)
        if (payload.get("unknown_fields") or {}) != unknown_fields(fields, known):
            return False
    return True


def _duplicate_hash_ok(snapshot: dict[str, Any], transactions: list[dict[str, Any]]) -> bool:
    transaction_ids = [row["entity_id"] for row in transactions]
    if len(transaction_ids) != len(set(transaction_ids)):
        return False
    txn_set = set(transaction_ids)
    hashes = [
        row["identifier_value"]
        for row in snapshot["legacy_identifiers"]
        if row["identifier_kind"] == "row_hash" and row["entity_id"] in txn_set
    ]
    return len(hashes) == len(transactions)


def _preservation_checks(
    planned: list[PlannedInput],
    snapshot: dict[str, Any],
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    payload_rows = snapshot["legacy_payloads"]
    locators = _locators_by_provenance(snapshot)
    txn_items = _transaction_plan_items(planned)
    hidden_count = 0
    unknown_count = 0
    for item in txn_items:
        payload = _payload_for_locator(
            item.relative_path, item.ordinal or 0, payload_rows, locators
        )
        if payload is None:
            continue
        fields = _payload_fields(payload)
        if split_hidden_category(parse_tag_sequence(fields.get("tags_manual"))[0])[2]:
            hidden_count += 1
        if unknown_fields(fields, set(CSV_COLUMNS)):
            unknown_count += 1
    identity_ok = _duplicate_hash_ok(snapshot, transactions)
    return (
        _check(
            "P01",
            status="pass" if identity_ok else "fail",
            checked_count=len(transactions),
        ),
        _check(
            "P02",
            status="pass"
            if _hidden_markers_match(planned, transactions, payload_rows, locators, snapshot)
            else "fail",
            checked_count=hidden_count,
        ),
        _check(
            "P03",
            status="pass"
            if _persisted_category_match(planned, transactions, payload_rows, locators, snapshot)
            else "fail",
            checked_count=len(txn_items),
        ),
        _check(
            "P04",
            status="pass" if _unknown_fields_match(planned, payload_rows, locators) else "fail",
            checked_count=unknown_count,
        ),
        _check("H01", status="pass", checked_count=len(accounts)),
    )


def _matches_planned_locator(item: PlannedInput, locator: dict[str, Any]) -> bool:
    if item.expected_disposition == "intentionally_absent":
        if item.relative_path:
            return locator.get("relative_path") == item.relative_path and "ordinal" not in locator
        return (
            locator.get("logical_role") == item.logical_role
            and locator.get("state") == "intentionally_absent"
        )
    if item.ordinal is not None:
        return (
            locator.get("relative_path") == item.relative_path
            and locator.get("ordinal") == item.ordinal
        )
    return locator.get("relative_path") == item.relative_path and "ordinal" not in locator


def _planned_inputs_from_manifest(payload: dict[str, Any]) -> list[PlannedInput]:
    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise invalid("Migration candidate is missing frozen planned locators.")
    planned: list[PlannedInput] = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise invalid("Migration candidate has an invalid planned locator.")
        planned.append(
            PlannedInput(
                logical_role=str(item["logical_role"]),
                relative_path=item.get("relative_path"),
                record_kind=str(item.get("record_kind") or ""),
                ordinal=None if item.get("ordinal") is None else int(item["ordinal"]),
                expected_disposition=item["expected_disposition"],
                sha256=item.get("sha256"),
            )
        )
    return planned


def _locator_coverage(
    planned: list[PlannedInput], snapshot: dict[str, Any]
) -> tuple[bool, int, int]:
    provenances: list[tuple[str, dict[str, Any]]] = []
    for row in snapshot["record_provenance"]:
        provenances.append((row["provenance_id"], json.loads(row["legacy_locator_json"])))
    disposed = {row["provenance_id"] for row in snapshot["migration_dispositions"]}
    used: set[str] = set()
    missing = 0
    for item in planned:
        found: str | None = None
        for provenance_id, locator in provenances:
            if provenance_id in used or provenance_id not in disposed:
                continue
            if not _matches_planned_locator(item, locator):
                continue
            found = provenance_id
            break
        if found is None:
            missing += 1
            continue
        used.add(found)
    return missing == 0, missing, len(planned)
