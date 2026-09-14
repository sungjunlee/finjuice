"""Detached portfolio source tables, without inferred identities or ownership."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.status_reads import ConfigHeadSnapshot, _head
from finjuice.pipeline.storage.sqlite.transaction_scopes import _source_scopes

Rows = tuple[dict[str, Any], ...]
_NATIVE = (
    "overview_balances",
    "overview_cashflows",
    "overview_insurance",
    "overview_investments",
    "overview_loans",
)
_LEGACY = (
    "legacy_overview_reports",
    "legacy_overview_balances",
    "legacy_overview_cashflows",
    "legacy_overview_insurance",
    "legacy_overview_investments",
    "legacy_overview_loans",
    "legacy_overview_reference_assessments",
    "legacy_overview_reference_candidates",
)
_TABLES = frozenset(
    (
        *_NATIVE,
        *_LEGACY,
        "asset_snapshots",
        "overview_facts",
        "config_revisions",
        "observations",
        "record_provenance",
        "legacy_payloads",
        "source_occurrences",
        "source_artifacts",
        "exact_values",
        "money_values",
        "quantity_values",
        "rate_values",
        "number_values",
        "accounts",
        "resources",
        "parties",
        "legacy_identifiers",
        "legacy_identifier_supersessions",
        "migration_identities",
        "ownership_assertion_sets",
        "ownership_assertion_shares",
        "entity_relation_assertions",
    )
)


@dataclass(frozen=True)
class PortfolioConfigSnapshot:
    """Missing selection is explicit; absent revisions do not imply an empty config."""

    head: ConfigHeadSnapshot | None
    selection_state: Literal["selected", "unselected", "absent"]
    revisions: Rows


@dataclass(frozen=True)
class PortfolioReadSnapshot:
    """Original table fields and linked evidence from one validated revision.

    Direct relation endpoints outside the portfolio are retained as IDs without
    recursively materializing unrelated entity domains.
    UUIDs and legacy aliases remain separate. Reported reference assessments are
    evidence, not verified fact links. Dictionaries are detached caller-owned data.
    """

    info: RepositoryInfo
    asset_snapshots: Rows
    overview_facts: Rows
    native_overview_reports: dict[str, Rows]
    legacy_overview_reports: dict[str, Rows]
    # Schema capability only; this does not assert report materialization completeness.
    legacy_reports_support: Literal["typed", "preserved_observations_only"]
    assets: PortfolioConfigSnapshot
    goals: PortfolioConfigSnapshot
    scenarios: PortfolioConfigSnapshot
    evidence: dict[str, Rows]
    source_scopes: Rows


def _rows(connection: sqlite3.Connection, table: str) -> Rows:
    if table not in _TABLES:
        raise ValueError("Unsupported portfolio evidence table.")
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY 1")
    names = [column[0] for column in cursor.description]
    return tuple(dict(zip(names, row, strict=True)) for row in cursor)


def _selected(
    connection: sqlite3.Connection, table: str, column: str, identifiers: set[str]
) -> Rows:
    if not identifiers:
        return ()
    if table not in _TABLES or column not in {
        "entity_id",
        "value_id",
        "provenance_id",
        "source_occurrence_id",
        "source_artifact_id",
        "previous_mapping_id",
        "account_id",
        "assertion_id",
        "subject_entity_id",
        "object_entity_id",
    }:
        raise ValueError("Unsupported portfolio evidence selection.")
    result: list[dict[str, Any]] = []
    ordered = sorted(identifiers)
    for start in range(0, len(ordered), 500):
        batch = ordered[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        cursor = connection.execute(
            f"SELECT * FROM {table} WHERE {column} IN ({placeholders}) ORDER BY 1", batch
        )
        names = [item[0] for item in cursor.description]
        result.extend(dict(zip(names, row, strict=True)) for row in cursor)
    return tuple(result)


def _ids(rows: Rows, *columns: str) -> set[str]:
    return {row[column] for row in rows for column in columns if row.get(column) is not None}


def _config(
    connection: sqlite3.Connection, paths: GenerationPaths, kind: str, revisions: Rows
) -> PortfolioConfigSnapshot:
    candidates = tuple(row for row in revisions if row["config_kind"] == kind)
    head = _head(connection, paths, kind)
    return PortfolioConfigSnapshot(
        head,
        "selected" if head is not None else "unselected" if candidates else "absent",
        candidates,
    )


def portfolio_snapshot(
    connection: sqlite3.Connection, info: RepositoryInfo, paths: GenerationPaths
) -> PortfolioReadSnapshot:
    """Materialize portfolio tables and reachable evidence without transaction rows."""
    assets = _rows(connection, "asset_snapshots")
    facts = _rows(connection, "overview_facts")
    native = {table: _rows(connection, table) for table in _NATIVE}
    legacy = (
        {table: _rows(connection, table) for table in _LEGACY} if info.schema_version >= 5 else {}
    )
    revisions = tuple(
        row
        for row in _rows(connection, "config_revisions")
        if row["config_kind"] in {"assets", "goals", "scenarios"}
    )
    domain = (
        assets + facts + tuple(row for rows in (*native.values(), *legacy.values()) for row in rows)
    )
    scopes = tuple(
        {"source_occurrence_id": occurrence, "capture_manifest_digest": capture, **locator}
        for occurrence, (capture, locator) in sorted(_source_scopes(connection).items())
        if _portfolio_path(locator["path"])
    )
    evidence = _evidence(connection, domain, revisions, scopes)
    return PortfolioReadSnapshot(
        info,
        assets,
        facts,
        native,
        legacy,
        "typed" if info.schema_version >= 5 else "preserved_observations_only",
        _config(connection, paths, "assets", revisions),
        _config(connection, paths, "goals", revisions),
        _config(connection, paths, "scenarios", revisions),
        evidence,
        scopes,
    )


def _portfolio_path(path: str) -> bool:
    # Match canonical partition roles, not arbitrary paths containing a domain name.
    match = re.fullmatch(
        r"(assets/snapshots|banksalad/(?:overview_facts|balance|cashflow|insurance|investments|loans))"
        r"/[0-9]{4}/(?:0[1-9]|1[0-2])/([^/]+)",
        path,
    )
    if match is None:
        return False
    role = match[1].split("/")[-1]
    expected = "facts.csv" if role == "overview_facts" else f"{role}.csv"
    return match[2] == expected


def _evidence(
    connection: sqlite3.Connection, domain: Rows, configs: Rows, scopes: Rows
) -> dict[str, Rows]:
    # Include unmaterialized native overview fragments, not only typed row endpoints.
    cursor = connection.execute(
        "SELECT prov.* FROM record_provenance AS prov "
        "JOIN source_occurrences AS source ON source.entity_id = prov.source_occurrence_id "
        "WHERE source.occurrence_kind = ? AND "
        "json_extract(prov.source_coordinate_json, '$.family') IN (?, ?, ?, ?) "
        "ORDER BY prov.provenance_id",
        (
            "exact_xlsx_import",
            "overview_fact",
            "overview_balance",
            "overview_investment",
            "overview_loan",
        ),
    )
    names = [column[0] for column in cursor.description]
    native_provenance = tuple(dict(zip(names, row, strict=True)) for row in cursor)
    scoped = _ids(scopes, "source_occurrence_id")
    observations = _selected(
        connection,
        "observations",
        "entity_id",
        _ids(domain, "observation_id", "candidate_observation_id"),
    )
    # Portfolio CSV containers include opaque rows and empty partition evidence.
    by_occurrence = _selected(connection, "observations", "source_occurrence_id", scoped)
    observations = tuple({row["entity_id"]: row for row in observations + by_occurrence}.values())
    provenance = _selected(
        connection,
        "record_provenance",
        "provenance_id",
        _ids(domain, "provenance_id", "candidate_provenance_id"),
    )
    file_provenance = _selected(
        connection,
        "record_provenance",
        "source_occurrence_id",
        scoped | _ids(configs, "source_occurrence_id"),
    )
    provenance = tuple(
        {
            row["provenance_id"]: row for row in provenance + file_provenance + native_provenance
        }.values()
    )
    occurrences = _selected(
        connection,
        "source_occurrences",
        "entity_id",
        scoped | _ids(observations + provenance + configs, "source_occurrence_id"),
    )
    values = {
        value
        for row in domain
        for key, value in row.items()
        if key.endswith("_value_id") and value is not None
    }
    accounts = _selected(connection, "accounts", "entity_id", _ids(domain, "account_id"))
    resources = _selected(connection, "resources", "entity_id", _ids(domain, "resource_id"))
    entities = _ids(
        domain + observations + accounts + resources + occurrences + configs, "entity_id"
    )
    aliases = _selected(connection, "legacy_identifiers", "entity_id", entities)
    relationships = _relationships(connection, accounts, entities)
    shares = relationships["ownership_assertion_shares"]
    values |= _ids(shares, "share_value_id")
    exact = _selected(connection, "exact_values", "value_id", values)
    value_provenance = _selected(
        connection, "record_provenance", "provenance_id", _ids(exact, "provenance_id")
    )
    provenance = tuple(
        {row["provenance_id"]: row for row in provenance + value_provenance}.values()
    )
    occurrences = _selected(
        connection,
        "source_occurrences",
        "entity_id",
        _ids(occurrences, "entity_id") | _ids(provenance, "source_occurrence_id"),
    )
    result = {
        **relationships,
        "observations": observations,
        "record_provenance": provenance,
        "legacy_payloads": _selected(
            connection, "legacy_payloads", "provenance_id", _ids(provenance, "provenance_id")
        ),
        "source_occurrences": occurrences,
        "source_artifacts": _selected(
            connection,
            "source_artifacts",
            "source_artifact_id",
            _ids(occurrences + configs, "source_artifact_id"),
        ),
        "exact_values": exact,
        "accounts": accounts,
        "resources": resources,
        "parties": _selected(
            connection,
            "parties",
            "entity_id",
            _ids(accounts, "owner_party_id") | _ids(shares, "party_id"),
        ),
        "legacy_identifiers": aliases,
        "legacy_identifier_supersessions": _selected(
            connection,
            "legacy_identifier_supersessions",
            "previous_mapping_id",
            _ids(aliases, "mapping_id"),
        ),
        "migration_identities": _selected(
            connection, "migration_identities", "entity_id", entities
        ),
    }
    for table in ("money_values", "quantity_values", "rate_values", "number_values"):
        result[table] = _selected(connection, table, "value_id", values)
    return result


def _relationships(
    connection: sqlite3.Connection, accounts: Rows, entities: set[str]
) -> dict[str, Rows]:
    assertions = _selected(
        connection, "ownership_assertion_sets", "account_id", _ids(accounts, "entity_id")
    )
    shares = _selected(
        connection, "ownership_assertion_shares", "assertion_id", _ids(assertions, "assertion_id")
    )
    subjects = _selected(connection, "entity_relation_assertions", "subject_entity_id", entities)
    objects = _selected(connection, "entity_relation_assertions", "object_entity_id", entities)
    relations = tuple({row["assertion_id"]: row for row in subjects + objects}.values())
    return {
        "ownership_assertion_sets": assertions,
        "ownership_assertion_shares": shares,
        "entity_relation_assertions": relations,
    }
