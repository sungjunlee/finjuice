"""Minimal detached transactions and config selections for analysis consumers."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot, _config, _rows
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.storage.sqlite.transaction_scopes import _month, _object, _source_scopes


@dataclass(frozen=True)
class AnalysisReadSnapshot:
    """Caller-owned analysis payloads materialized from a single reader revision."""

    info: RepositoryInfo
    transactions: TransactionReadSnapshot
    rules: PortfolioConfigSnapshot
    goals: PortfolioConfigSnapshot
    unmaterialized_months: tuple[str, ...] = ()


def analysis_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths, transactions: TransactionReadSnapshot
) -> AnalysisReadSnapshot:
    """Read config inventories once without loading portfolio or import domains."""
    revisions = _rows(connection, "config_revisions")
    return deepcopy(
        AnalysisReadSnapshot(
            transactions.info,
            transactions,
            _config(connection, paths, "rules", revisions),
            _config(connection, paths, "goals", revisions),
            unmaterialized_transaction_months(connection),
        )
    )


_UNMATERIALIZED_SQL = """
SELECT prov.source_occurrence_id, prov.source_coordinate_json, prov.legacy_locator_json,
       payload.payload_json, identity.capture_manifest_digest, identity.canonical_locator_json,
       observation.source_occurrence_id, disposition.disposition, disposition.reason
FROM record_provenance AS prov
JOIN legacy_payloads AS payload USING (provenance_id)
JOIN migration_identities AS source_identity
    ON source_identity.entity_id = prov.source_occurrence_id
    AND source_identity.record_kind = 'source_occurrence'
LEFT JOIN migration_identities AS identity
    ON identity.capture_manifest_digest = source_identity.capture_manifest_digest
    AND identity.record_kind = 'observation'
    AND identity.canonical_locator_json = prov.legacy_locator_json
LEFT JOIN observations AS observation ON observation.entity_id = identity.entity_id
    AND observation.source_occurrence_id = prov.source_occurrence_id
LEFT JOIN migration_dispositions AS disposition USING (provenance_id)
WHERE NOT EXISTS (
    SELECT 1 FROM transactions AS txn WHERE txn.provenance_id = prov.provenance_id
)
"""


def unmaterialized_transaction_months(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Find proven primary CSV rows/parse failures that have no typed transaction."""
    sources = _source_scopes(connection)
    return tuple(
        sorted(
            {
                month
                for row in connection.execute(_UNMATERIALIZED_SQL)
                if (month := _unmaterialized_month(tuple(row), sources)) is not None
            }
        )
    )


def _unmaterialized_month(
    row: tuple[Any, ...], sources: dict[str, tuple[str, dict[str, Any]]]
) -> str | None:
    occurrence, coordinate, legacy, payload, capture, identity, observed, disposition, reason = row
    source = sources.get(occurrence)
    locator, raw = _object(coordinate), _object(payload)
    if source is None or locator is None or raw is None:
        return None
    expected_capture, file_locator = source
    month = _month(file_locator)
    if month is None or locator != _object(legacy) or {**locator, "row": None} != file_locator:
        return None
    ordinal = locator.get("row")
    if ordinal is None:
        return month if disposition == "preserved_opaque" and reason == "csv_parse_failed" else None
    if (
        type(ordinal) is not int
        or ordinal < 1
        or not all(isinstance(raw.get(key), list) for key in ("columns", "values", "cells"))
        or not isinstance(raw.get("raw_record"), str)
    ):
        return None
    if observed is not None:
        return (
            month
            if observed == occurrence
            and capture == expected_capture
            and _object(identity) == locator
            else None
        )
    # Duplicate columns/ragged rows deliberately have no observation identity.
    return month if capture is None and disposition == "preserved_opaque" else None
