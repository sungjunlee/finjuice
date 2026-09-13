"""Additive schema v5 for reported legacy overview values and reference evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Final

from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError, RepositoryVersionError

LEGACY_OVERVIEW_TABLES: Final = (
    "legacy_overview_reports",
    "legacy_overview_balances",
    "legacy_overview_cashflows",
    "legacy_overview_insurance",
    "legacy_overview_investments",
    "legacy_overview_loans",
    "legacy_overview_reference_assessments",
    "legacy_overview_reference_candidates",
)

_SCHEMA_SQL: Final = """
CREATE TABLE legacy_overview_reports (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES observations(entity_id),
 provenance_id TEXT UNIQUE NOT NULL REFERENCES record_provenance(provenance_id),
 report_kind TEXT NOT NULL CHECK(
    report_kind IN ('balance','cashflow','insurance','investment','loan')),
 snapshot_date TEXT NOT NULL CHECK(length(snapshot_date) > 0)
);
CREATE TABLE legacy_overview_balances (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
 side TEXT,
 category TEXT,
 item_name TEXT,
 currency TEXT
);
CREATE TABLE legacy_overview_cashflows (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
 period_month TEXT,
 category TEXT,
 currency TEXT
);
CREATE TABLE legacy_overview_insurance (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 institution TEXT,
 policy_name TEXT,
 contract_status TEXT,
 contract_date TEXT,
 maturity_date TEXT,
 paid_amount_value_id TEXT REFERENCES money_values(value_id),
 currency TEXT
);
CREATE TABLE legacy_overview_investments (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 product_type TEXT,
 institution TEXT,
 product_name TEXT,
 start_date TEXT,
 maturity_date TEXT,
 principal_value_id TEXT REFERENCES money_values(value_id),
 valuation_value_id TEXT REFERENCES money_values(value_id),
 return_rate_value_id TEXT REFERENCES rate_values(value_id),
 currency TEXT
);
CREATE TABLE legacy_overview_loans (
 observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 loan_type TEXT,
 institution TEXT,
 product_name TEXT,
 start_date TEXT,
 maturity_date TEXT,
 principal_value_id TEXT REFERENCES money_values(value_id),
 balance_value_id TEXT REFERENCES money_values(value_id),
 interest_rate_value_id TEXT REFERENCES rate_values(value_id),
 currency TEXT
);
CREATE TABLE legacy_overview_reference_assessments (
 report_observation_id TEXT PRIMARY KEY NOT NULL REFERENCES legacy_overview_reports(observation_id),
 capture_digest TEXT NOT NULL CHECK(length(capture_digest) = 64
    AND capture_digest NOT GLOB '*[^0-9a-f]*'),
 source_fact_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('missing','unverified','ambiguous')),
 assessment_policy TEXT NOT NULL CHECK(assessment_policy = 'legacy_overview_reference.v1')
);
CREATE TABLE legacy_overview_reference_candidates (
 report_observation_id TEXT NOT NULL
    REFERENCES legacy_overview_reference_assessments(report_observation_id),
 candidate_observation_id TEXT NOT NULL REFERENCES observations(entity_id),
 candidate_provenance_id TEXT NOT NULL REFERENCES record_provenance(provenance_id),
 PRIMARY KEY(report_observation_id, candidate_provenance_id)
);
"""


def _immutable_guards() -> str:
    statements = []
    for table in LEGACY_OVERVIEW_TABLES:
        for operation in ("UPDATE", "DELETE"):
            statements.append(
                f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;"
            )
        if table == "legacy_overview_reports":
            conflict = "observation_id = NEW.observation_id OR provenance_id = NEW.provenance_id"
        elif table == "legacy_overview_reference_candidates":
            conflict = (
                "report_observation_id = NEW.report_observation_id AND "
                "candidate_provenance_id = NEW.candidate_provenance_id"
            )
        elif table == "legacy_overview_reference_assessments":
            conflict = "report_observation_id = NEW.report_observation_id"
        else:
            conflict = "observation_id = NEW.observation_id"
        statements.append(
            f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
            f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {conflict}) "
            "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;"
        )
    return "\n".join(statements)


def apply_schema_v5(connection: sqlite3.Connection) -> None:
    """Add empty report tables without reinterpreting any v4 evidence."""
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 4:
        raise RepositoryVersionError("Schema v5 requires a schema v4 repository.")
    guards = _immutable_guards()
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA_SQL + guards)
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (5, 'legacy_reported_overview', ?)",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),),
        )
        connection.execute("UPDATE repository_meta SET schema_version = 5 WHERE singleton = 1")
        connection.execute("PRAGMA user_version = 5")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


# Detail names and value roles are fixed schema metadata, never caller SQL.
_DETAIL_TABLES: Final = {
    "balance": "legacy_overview_balances",
    "cashflow": "legacy_overview_cashflows",
    "insurance": "legacy_overview_insurance",
    "investment": "legacy_overview_investments",
    "loan": "legacy_overview_loans",
}
_VALUE_FIELDS: Final = {
    "balance": (("amount_value_id", "money", None),),
    "cashflow": (("amount_value_id", "money", None),),
    "insurance": (("paid_amount_value_id", "money", None),),
    "investment": (
        ("principal_value_id", "money", None),
        ("valuation_value_id", "money", None),
        ("return_rate_value_id", "rate", "legacy_overview_return_rate.v1"),
    ),
    "loan": (
        ("principal_value_id", "money", None),
        ("balance_value_id", "money", None),
        ("interest_rate_value_id", "rate", "legacy_overview_interest_rate.v1"),
    ),
}


def _invalid() -> RepositoryIntegrityError:
    return RepositoryIntegrityError("Legacy overview report evidence is inconsistent.")


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _payload_row(payload: str) -> dict[str, str | None]:
    """Read the preserved cell states without importing a mutable adapter."""
    try:
        data = json.loads(payload)
        columns, cells = data["columns"], data["cells"]
        if not isinstance(columns, list) or len(set(columns)) != len(columns):
            raise _invalid()
        if not isinstance(cells, list) or len(cells) != len(columns):
            raise _invalid()
        result: dict[str, str | None] = {}
        for index, cell in enumerate(cells):
            if cell["column"] != columns[index] or cell["column_ordinal"] != index:
                raise _invalid()
            state, value = cell["state"], cell["value"]
            if state not in {"null", "missing", "blank", "value"}:
                raise _invalid()
            if value is not None and not isinstance(value, str):
                raise _invalid()
            result[cell["column"]] = None if state in {"null", "missing"} else value
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid() from exc


def _source_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = _rows(
        connection,
        """
        SELECT o.entity_id AS observation_id, o.source_occurrence_id,
            p.provenance_id, p.legacy_locator_json, p.source_coordinate_json,
            i.capture_manifest_digest AS capture_digest, i.canonical_locator_json,
            oi.capture_manifest_digest AS occurrence_capture,
            oi.canonical_locator_json AS occurrence_locator, payload.payload_json
        FROM observations o
        JOIN migration_identities i ON i.entity_id = o.entity_id
        JOIN record_provenance p ON p.source_occurrence_id = o.source_occurrence_id
            AND p.legacy_locator_json = i.canonical_locator_json
        JOIN migration_identities oi ON oi.entity_id = o.source_occurrence_id
        JOIN legacy_payloads payload ON payload.provenance_id = p.provenance_id
    """,
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["observation_id"]
        if identifier in result:
            raise _invalid()
        result[identifier] = row
    expected = {
        row[0]
        for row in connection.execute(
            "SELECT entity_id FROM migration_identities WHERE record_kind = 'observation'"
        )
    }
    if set(result) != expected:
        raise _invalid()
    return result


def _validate_source(row: dict[str, Any], capture: str, provenance: str) -> None:
    if row["capture_digest"] != capture or row["occurrence_capture"] != capture:
        raise _invalid()
    if row["provenance_id"] != provenance:
        raise _invalid()
    try:
        locator = json.loads(row["canonical_locator_json"])
        coordinate = json.loads(row["source_coordinate_json"])
        occurrence = json.loads(row["occurrence_locator"])
        if (
            locator != coordinate
            or type(locator["row"]) is not int
            or locator["row"] < 1
            or occurrence != {**locator, "row": None}
        ):
            raise _invalid()
    except (TypeError, KeyError, ValueError) as exc:
        raise _invalid() from exc


def _validate_unit(
    connection: sqlite3.Connection,
    identifier: str,
    kind: str,
    unit: str | None,
    currency: str | None,
) -> None:
    if kind == "rate":
        row = connection.execute(
            "SELECT unit FROM rate_values WHERE value_id = ?", (identifier,)
        ).fetchone()
        expected: tuple[Any, ...] = (unit,)
    else:
        row = connection.execute(
            "SELECT currency_code, currency_unknown FROM money_values WHERE value_id = ?",
            (identifier,),
        ).fetchone()
        expected = (None, 1) if currency in (None, "") else (currency, 0)
    if row is None or tuple(row) != expected:
        raise _invalid()


def _validate_text(
    report: dict[str, Any],
    detail: dict[str, Any],
    raw: dict[str, str | None],
) -> None:
    for field, text in detail.items():
        if field == "observation_id" or field.endswith("_value_id"):
            continue
        expected = raw.get(field)
        if field == "currency" and report["report_kind"] == "cashflow":
            expected = None
        if text != expected:
            raise _invalid()


def _validate_values(
    connection: sqlite3.Connection,
    report: dict[str, Any],
    detail: dict[str, Any],
    raw: dict[str, str | None],
) -> None:
    _validate_text(report, detail, raw)
    for field, kind, unit in _VALUE_FIELDS[report["report_kind"]]:
        source_field = field.removesuffix("_value_id")
        if source_field in {"principal", "valuation", "balance"}:
            source_field += "_amount"
        identifier = detail[field]
        if identifier is None:
            if raw.get(source_field) is not None:
                raise _invalid()
            continue
        value = connection.execute(
            "SELECT value_kind, provenance_id, origin_kind, lexical FROM exact_values "
            "WHERE value_id = ?",
            (identifier,),
        ).fetchone()
        expected = (kind, report["provenance_id"], "migration", raw.get(source_field))
        if value is None or tuple(value) != expected:
            raise _invalid()
        _validate_unit(connection, identifier, kind, unit, detail["currency"])


def _source_path(source: dict[str, Any]) -> tuple[str, ...]:
    try:
        return PurePosixPath(json.loads(source["canonical_locator_json"])["path"]).parts
    except (TypeError, KeyError, ValueError) as exc:
        raise _invalid() from exc


def _report_source_kind(parts: tuple[str, ...]) -> str | None:
    """Freeze canonical v4 adapter report dispatch independently of runtime code."""
    roles = {
        "balance": "balance",
        "cashflow": "cashflow",
        "insurance": "insurance",
        "investments": "investment",
        "loans": "loan",
    }
    if len(parts) != 5 or parts[0] != "banksalad" or parts[1] not in roles:
        return None
    if not (len(parts[2]) == 4 and parts[2].isascii() and parts[2].isdigit()):
        return None
    if parts[3] not in {f"{month:02d}" for month in range(1, 13)}:
        return None
    return roles[parts[1]] if parts[4] == f"{parts[1]}.csv" else None


def _fact_source_path(source: dict[str, Any]) -> bool:
    parts = _source_path(source)
    return "transactions" not in parts and _report_source_kind(parts) is None


def _fact_index(
    source_rows: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], set[tuple[str, str]]]:
    result: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for identifier, source in source_rows.items():
        if not _fact_source_path(source):
            continue
        raw = _payload_row(source["payload_json"])
        alias = raw.get("fact_id")
        if alias is not None and "fact_kind" in raw:
            key = (source["capture_digest"], alias)
            result.setdefault(key, set()).add((identifier, source["provenance_id"]))
    return result


def _validate_reference(
    assessment: dict[str, Any],
    actual: set[tuple[str, str]],
    fact_index: dict[tuple[str, str], set[tuple[str, str]]],
    source_rows: dict[str, dict[str, Any]],
) -> None:
    alias, capture = assessment["source_fact_id"], assessment["capture_digest"]
    expected = fact_index.get((capture, alias), set()) if alias is not None else set()
    if actual != expected:
        raise _invalid()
    status = "missing" if not actual else "unverified" if len(actual) == 1 else "ambiguous"
    if assessment["status"] != status:
        raise _invalid()
    for candidate_id, provenance in actual:
        _validate_source(source_rows[candidate_id], capture, provenance)


_REPORT_ROWS_SQL: Final = "SELECT * FROM legacy_overview_reports"


def validate_v5_invariants(connection: sqlite3.Connection) -> None:
    """Validate report closure and the complete capture-bound unselected candidate set."""
    reports = _rows(connection, _REPORT_ROWS_SQL)
    details = {
        kind: {row["observation_id"]: row for row in _rows(connection, f"SELECT * FROM {table}")}
        for kind, table in _DETAIL_TABLES.items()
    }
    assessments = {
        row["report_observation_id"]: row
        for row in _rows(connection, "SELECT * FROM legacy_overview_reference_assessments")
    }
    source_rows = _source_rows(connection) if reports else {}
    fact_index = _fact_index(source_rows)
    candidates: dict[str, set[tuple[str, str]]] = {}
    for row in _rows(connection, "SELECT * FROM legacy_overview_reference_candidates"):
        candidates.setdefault(row["report_observation_id"], set()).add(
            (row["candidate_observation_id"], row["candidate_provenance_id"])
        )
    for report in reports:
        identifier, kind = report["observation_id"], report["report_kind"]
        if {key for key, values in details.items() if identifier in values} != {kind}:
            raise _invalid()
        assessment = assessments.get(identifier)
        report_source = source_rows.get(identifier)
        if assessment is None or report_source is None:
            raise _invalid()
        if _report_source_kind(_source_path(report_source)) != kind:
            raise _invalid()
        capture = assessment["capture_digest"]
        _validate_source(report_source, capture, report["provenance_id"])
        raw = _payload_row(report_source["payload_json"])
        if raw.get("source_fact_id") != assessment["source_fact_id"]:
            raise _invalid()
        if raw.get("snapshot_date") != report["snapshot_date"]:
            raise _invalid()
        _validate_values(connection, report, details[kind][identifier], raw)
        _validate_reference(assessment, candidates.get(identifier, set()), fact_index, source_rows)
