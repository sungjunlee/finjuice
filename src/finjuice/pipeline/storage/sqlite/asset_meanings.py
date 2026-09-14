"""Canonical source evidence and explicit asset interpretation commands."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping

from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id

# Closed table list. These values remain original evidence, never materialized corrections.
SOURCE_TABLES = (
    "asset_snapshots",
    "overview_facts",
    "overview_balances",
    "overview_cashflows",
    "overview_insurance",
    "overview_investments",
    "overview_loans",
)
MEASURES = {
    "balance",
    "holding_quantity",
    "valuation",
    "cash_movement",
    "right_obligation",
    "expected_inflow",
}
SOURCES = {"screenshot", "institution_export", "manual", "workbook_summary", "workbook_holdings"}


def rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Read a closed canonical evidence surface."""
    allowed = {
        *SOURCE_TABLES,
        "asset_meaning_assertions",
        "observations",
        "record_provenance",
        "source_occurrences",
        "source_artifacts",
        "exact_values",
        "money_values",
        "rate_values",
        "entity_relation_assertions",
        "legacy_overview_reports",
    }
    if table not in allowed:
        raise ValueError("Unsupported asset evidence table.")
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY 1")
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def asset_sources(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return actual linked observation/provenance, preserving original values and states."""
    observations = {row["entity_id"]: row for row in rows(connection, "observations")}
    provenance = {row["provenance_id"]: row for row in rows(connection, "record_provenance")}
    result = {}
    for table in SOURCE_TABLES:
        for row in rows(connection, table):
            observed = observations[row["observation_id"]]
            origin = provenance[row["provenance_id"]]
            result[row["entity_id"]] = {
                "source_entity_id": row["entity_id"],
                "source_table": table,
                "observation": observed,
                "provenance_id": row["provenance_id"],
                "source_occurrence_id": origin["source_occurrence_id"],
                "source_date": row.get("snapshot_date"),
                "value_ids": sorted(
                    {
                        value
                        for key, value in row.items()
                        if key.endswith("_value_id") and value is not None
                    }
                ),
                "original_account_id": row.get("account_id"),
                "original_resource_id": row.get("resource_id"),
            }
    return result


@dataclass(frozen=True)
class AssetMeaningDecision:
    source_entity_id: str
    value_id: str
    account_id: str
    measure_kind: str
    source_kind: str
    as_of: str
    scope_state: str
    evidence: Mapping[str, Any]
    resource_id: str | None = None
    original_currency: str | None = None
    net_worth_sign: int = 1
    confirmation_state: str = "confirmed"
    fx: Mapping[str, Any] | None = None
    supersedes_assertion_id: str | None = None


def _evidence(value: Any) -> str:
    if not isinstance(value, Mapping) or not value:
        raise MutationValidationError("Explicit non-empty evidence is required.")
    return json.dumps(dict(value), sort_keys=True, allow_nan=False)


def _date(value: str) -> None:
    if date.fromisoformat(value).isoformat() != value:
        raise MutationValidationError("Asset dates must use YYYY-MM-DD.")


def validate_decision(connection: sqlite3.Connection, command: AssetMeaningDecision) -> None:
    """Reject interpretations detached from the referenced canonical source value."""
    for identifier in (command.source_entity_id, command.value_id, command.account_id):
        validate_entity_id(identifier)
    _date(command.as_of)
    _evidence(command.evidence)
    if command.measure_kind not in MEASURES or command.source_kind not in SOURCES:
        raise MutationValidationError("Unsupported explicit asset meaning or source kind.")
    if command.scope_state not in {
        "complete",
        "partial",
        "unknown",
    } or command.confirmation_state not in {"confirmed", "unconfirmed", "rejected"}:
        raise MutationValidationError("Unsupported asset scope or confirmation state.")
    if type(command.net_worth_sign) is not int or command.net_worth_sign not in {-1, 1}:
        raise MutationValidationError("Asset sign must be explicit +1 or -1.")
    source = asset_sources(connection).get(command.source_entity_id)
    if source is None or command.value_id not in source["value_ids"]:
        raise MutationValidationError("Asset meaning value is not linked to its source entity.")
    kind = connection.execute(
        "SELECT value_kind FROM exact_values WHERE value_id = ?", (command.value_id,)
    ).fetchone()[0]
    if (command.measure_kind == "holding_quantity" and kind != "quantity") or (
        command.measure_kind != "holding_quantity" and kind not in {"money", "number"}
    ):
        raise MutationValidationError("Measure is incompatible with the original exact value kind.")
    _validate_currency(connection, command)


def _validate_currency(connection: sqlite3.Connection, command: AssetMeaningDecision) -> None:
    if command.original_currency is not None and not re.fullmatch(
        r"[A-Z]{3}", command.original_currency
    ):
        raise MutationValidationError("Currency must be an explicit ISO-style three-letter code.")
    money = connection.execute(
        "SELECT currency_code FROM money_values WHERE value_id = ?", (command.value_id,)
    ).fetchone()
    if money and money[0] is not None and money[0] != command.original_currency:
        raise MutationValidationError(
            "Original source currency cannot be changed by interpretation."
        )
    if command.fx is not None:
        if set(command.fx) != {"coefficient", "scale", "quote_currency", "as_of", "evidence"}:
            raise MutationValidationError(
                "FX requires exact rate, quote currency, date and evidence."
            )
        _date(command.fx["as_of"])
        _evidence(command.fx["evidence"])
        if not isinstance(command.fx["quote_currency"], str) or not re.fullmatch(
            r"[A-Z]{3}", command.fx["quote_currency"]
        ):
            raise MutationValidationError("FX quote currency is invalid.")
        if command.original_currency is None:
            raise MutationValidationError("FX cannot supply missing original currency.")


def insert_asset_meaning(
    connection: sqlite3.Connection,
    command: AssetMeaningDecision,
    changeset_id: str,
    fx_value_id: str | None,
) -> dict[str, Any]:
    """Append one interpretation; earlier evidence and source observations are immutable."""
    validate_decision(connection, command)
    heads = connection.execute(
        "SELECT a.assertion_id FROM asset_meaning_assertions a WHERE source_entity_id = ? "
        "AND NOT EXISTS(SELECT 1 FROM asset_meaning_assertions n "
        "WHERE n.supersedes_assertion_id = a.assertion_id)",
        (command.source_entity_id,),
    ).fetchall()
    if heads and [row[0] for row in heads] != [command.supersedes_assertion_id]:
        raise MutationConflictError("Correct the current meaning assertion explicitly.")
    if not heads and command.supersedes_assertion_id is not None:
        raise MutationConflictError("Meaning correction target does not exist for this source.")
    identifier = new_entity_id()
    fx = command.fx
    connection.execute(
        "INSERT INTO asset_meaning_assertions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            command.source_entity_id,
            command.value_id,
            command.account_id,
            command.resource_id,
            command.measure_kind,
            command.source_kind,
            command.as_of,
            command.scope_state,
            command.confirmation_state,
            command.original_currency,
            command.net_worth_sign,
            fx_value_id,
            fx["quote_currency"] if fx else None,
            fx["as_of"] if fx else None,
            _evidence(fx["evidence"]) if fx else None,
            _evidence(command.evidence),
            command.supersedes_assertion_id,
            changeset_id,
        ),
    )
    return {"assertion_id": identifier, "fx_value_id": fx_value_id, **asdict(command)}


def validate_asset_meanings(connection: sqlite3.Connection) -> None:
    """Validate stored assertions on every supported reader and commit boundary."""
    from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError

    meanings = rows(connection, "asset_meaning_assertions")
    by_id = {row["assertion_id"]: row for row in meanings}
    try:
        for row in meanings:
            validate_entity_id(row["assertion_id"])
            fx = None
            if row["fx_value_id"] is not None:
                exact = connection.execute(
                    "SELECT coefficient, scale FROM exact_values WHERE value_id = ?",
                    (row["fx_value_id"],),
                ).fetchone()
                unit = connection.execute(
                    "SELECT unit FROM rate_values WHERE value_id = ?", (row["fx_value_id"],)
                ).fetchone()
                if (
                    exact is None
                    or (exact[0] == "0" or exact[0].startswith("-"))
                    or unit[0] != "fx_rate.v1"
                ):
                    raise ValueError("Invalid FX basis.")
                fx = {
                    "coefficient": exact[0],
                    "scale": exact[1],
                    "quote_currency": row["fx_quote_currency"],
                    "as_of": row["fx_as_of"],
                    "evidence": json.loads(row["fx_evidence_json"]),
                }
            command = AssetMeaningDecision(
                **{
                    key: row[key]
                    for key in (
                        "source_entity_id",
                        "value_id",
                        "account_id",
                        "measure_kind",
                        "source_kind",
                        "as_of",
                        "scope_state",
                        "resource_id",
                        "original_currency",
                        "net_worth_sign",
                        "confirmation_state",
                        "supersedes_assertion_id",
                    )
                },
                evidence=json.loads(row["evidence_json"]),
                fx=fx,
            )
            validate_decision(connection, command)
            seen = {row["assertion_id"]}
            previous = row["supersedes_assertion_id"]
            while previous is not None:
                if (
                    previous in seen
                    or by_id[previous]["source_entity_id"] != row["source_entity_id"]
                ):
                    raise ValueError("Invalid asset meaning correction chain.")
                seen.add(previous)
                previous = by_id[previous]["supersedes_assertion_id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise RepositoryIntegrityError("Asset meaning evidence is inconsistent.") from exc
