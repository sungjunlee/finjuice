"""Pinned, exact transaction projections for repository consumers."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.sqlite.errors import ObjectCorruptionError
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.transaction_scopes import TransactionScope, transaction_scopes


@dataclass(frozen=True)
class TransactionReadSnapshot:
    """Detached rows and canonical rules from one validated repository snapshot.

    Decimal fields are exact text, tags remain JSON, and aliases never replace
    transaction identity. Dictionaries are detached copies, not database handles.
    """

    info: RepositoryInfo
    rows: tuple[dict[str, Any], ...]
    rules_content: bytes | None
    rules_parsed_status: str | None = None
    scopes: tuple[TransactionScope, ...] = ()
    partition_months: tuple[str, ...] = ()


_SQL = """
SELECT txn.*, amount.coefficient AS amount_coefficient, amount.scale AS amount_scale,
       amount.lexical AS amount_lexical, money.currency_code AS currency,
       money.currency_unknown, confidence.coefficient AS confidence_coefficient,
       confidence.scale AS confidence_scale
FROM transactions AS txn
JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id
JOIN money_values AS money ON money.value_id = txn.amount_value_id
LEFT JOIN exact_values AS confidence ON confidence.value_id = txn.confidence_value_id
ORDER BY txn.entity_id
"""
_ALIAS_SQL = """
SELECT mapping.entity_id, mapping.identifier_kind, mapping.identifier_value
FROM legacy_identifiers AS mapping
JOIN transactions AS txn ON txn.entity_id = mapping.entity_id
    AND txn.provenance_id = mapping.provenance_id
JOIN record_provenance AS provenance ON provenance.provenance_id = txn.provenance_id
JOIN observations AS observation ON observation.entity_id = txn.observation_id
    AND observation.source_occurrence_id = provenance.source_occurrence_id
WHERE mapping.identifier_kind IN ('row_hash', 'file_id', 'source_row')
    AND NOT EXISTS (SELECT 1 FROM legacy_identifier_supersessions AS supersession
                    WHERE supersession.previous_mapping_id = mapping.mapping_id)
"""


def transaction_snapshot(
    connection: sqlite3.Connection, info: RepositoryInfo, paths: GenerationPaths
) -> TransactionReadSnapshot:
    """Materialize the current typed state without recomputing classification."""
    aliases: dict[tuple[str, str], set[str]] = {}
    for entity, kind, value in connection.execute(_ALIAS_SQL):
        aliases.setdefault((entity, kind), set()).add(value)
    cursor = connection.execute(_SQL)
    names = [column[0] for column in cursor.description]
    rows = tuple(_row(dict(zip(names, values, strict=True)), aliases) for values in cursor)
    rules_content, rules_parsed_status = _rules_content(connection, paths)
    scopes, months = transaction_scopes(connection, tuple(row["transaction_id"] for row in rows))
    return TransactionReadSnapshot(info, rows, rules_content, rules_parsed_status, scopes, months)


def _decimal(coefficient: str | None, scale: int | None) -> str | None:
    if coefficient is None or scale is None:
        return None
    negative = coefficient.startswith("-")
    digits = coefficient.removeprefix("-")
    if scale:
        digits = digits.zfill(scale + 1)
        digits = f"{digits[:-scale]}.{digits[-scale:]}"
    return f"-{digits}" if negative else digits


def _row(raw: dict[str, Any], aliases: dict[tuple[str, str], set[str]]) -> dict[str, Any]:
    row = {column: raw.get(column) for column in CSV_COLUMNS}
    row.update(
        transaction_id=raw["entity_id"],
        account=raw["account_text"],
        date=raw["date_raw"],
        time=raw["time_raw"],
        datetime=raw["datetime_raw"],
        amount=_decimal(raw["amount_coefficient"], raw["amount_scale"]),
        confidence=_decimal(raw["confidence_coefficient"], raw["confidence_scale"]),
    )
    for name in ("tags_rule", "tags_ai", "tags_manual", "tags_final"):
        row[name] = raw[f"{name}_json"]
    for name in ("row_hash", "file_id", "source_row"):
        values = aliases.get((raw["entity_id"], name), set())
        row[name] = next(iter(values)) if len(values) == 1 else None
    for name in (
        "category_manual",
        "amount_coefficient",
        "amount_scale",
        "amount_lexical",
        "currency_unknown",
        "confidence_coefficient",
        "confidence_scale",
        "timezone_state",
        "observation_id",
        "provenance_id",
        "account_id",
    ):
        row[name] = raw[name]
    return row


def _rules_content(
    connection: sqlite3.Connection, paths: GenerationPaths
) -> tuple[bytes | None, str | None]:
    row = connection.execute(
        "SELECT revision.source_artifact_id, artifact.byte_length, revision.parsed_status "
        "FROM config_heads AS head "
        "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
        "JOIN source_artifacts AS artifact "
        "ON artifact.source_artifact_id = revision.source_artifact_id "
        "WHERE head.config_kind = 'rules'"
    ).fetchone()
    if row is None:
        return None, None
    artifact = SourceObjectStore(paths).verify(str(row[0]), int(row[1]))
    content = (paths.root / artifact.relative_path).read_bytes()
    if (
        len(content) != artifact.byte_length
        or hashlib.sha256(content).hexdigest() != artifact.digest_hex
    ):
        raise ObjectCorruptionError("Canonical rules changed while being read.")
    return content, str(row[2])
