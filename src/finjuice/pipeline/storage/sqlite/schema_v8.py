"""Canonical purchase evidence and append-only N:M settlement decisions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from finjuice.pipeline.storage.sqlite.errors import RepositoryVersionError

TABLE_KEYS = {
    "reconcile_evidence": ("evidence_id",),
    "reconcile_allocations": ("allocation_id",),
    "reconcile_allocation_evidence": ("allocation_id", "evidence_id"),
    "reconcile_allocation_payments": ("allocation_id", "transaction_id"),
    "reconcile_withdrawals": ("withdrawal_id",),
}

_SCHEMA = """
CREATE TABLE reconcile_evidence (
 evidence_id TEXT PRIMARY KEY NOT NULL,
 source_namespace TEXT NOT NULL CHECK(length(source_namespace)>0),
 external_key TEXT NOT NULL CHECK(length(external_key)>0),
 occurrence_id TEXT NOT NULL REFERENCES source_occurrences(entity_id),
 provenance_id TEXT NOT NULL REFERENCES record_provenance(provenance_id),
 evidence_kind TEXT NOT NULL CHECK(evidence_kind IN
 ('purchase','order','line_item','payment_evidence')),
 parent_evidence_id TEXT REFERENCES reconcile_evidence(evidence_id) DEFERRABLE INITIALLY DEFERRED,
 settlement_unit INTEGER NOT NULL CHECK(settlement_unit IN (0,1)),
 transaction_id TEXT REFERENCES transactions(entity_id),
 occurred_on TEXT NOT NULL,
 amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
 detail_json TEXT NOT NULL,
 payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64),
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
 DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(source_namespace, external_key),
 CHECK(evidence_id <> coalesce(parent_evidence_id,'')),
 CHECK((evidence_kind='payment_evidence' AND transaction_id IS NOT NULL AND settlement_unit=0)
 OR (evidence_kind<>'payment_evidence' AND transaction_id IS NULL))
);
CREATE TABLE reconcile_allocations (
 allocation_id TEXT PRIMARY KEY NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('matched','partial')),
 residual_value_id TEXT NOT NULL REFERENCES money_values(value_id),
 reason TEXT NOT NULL CHECK(length(reason)>0),
 confirmed_at TEXT NOT NULL,
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
 DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE reconcile_allocation_evidence (
 allocation_id TEXT NOT NULL REFERENCES reconcile_allocations(allocation_id),
 evidence_id TEXT NOT NULL REFERENCES reconcile_evidence(evidence_id),
 PRIMARY KEY(allocation_id,evidence_id)
);
CREATE TABLE reconcile_allocation_payments (
 allocation_id TEXT NOT NULL REFERENCES reconcile_allocations(allocation_id),
 transaction_id TEXT NOT NULL REFERENCES transactions(entity_id),
 PRIMARY KEY(allocation_id,transaction_id)
);
CREATE TABLE reconcile_withdrawals (
 withdrawal_id TEXT PRIMARY KEY NOT NULL,
 allocation_id TEXT NOT NULL UNIQUE REFERENCES reconcile_allocations(allocation_id),
 reason TEXT NOT NULL CHECK(length(reason)>0),
 withdrawn_at TEXT NOT NULL,
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
 DEFERRABLE INITIALLY DEFERRED
);
"""


def apply_schema_v8(connection: sqlite3.Connection) -> None:
    """Add empty settlement evidence; never infer links during upgrade."""
    if connection.execute("PRAGMA user_version").fetchone()[0] != 7:
        raise RepositoryVersionError("Schema v8 requires schema v7.")
    triggers = []
    for table, keys in TABLE_KEYS.items():
        predicate = " AND ".join(f"{key}=NEW.{key}" for key in keys)
        for action in ("UPDATE", "DELETE"):
            triggers.append(
                f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'immutable reconcile evidence'); END;"
            )
        triggers.append(
            f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
            f"WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) "
            "BEGIN SELECT RAISE(ABORT,'immutable reconcile evidence'); END;"
        )
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\n".join(triggers))
        connection.execute(
            "INSERT INTO schema_migrations VALUES (8, 'canonical_reconcile', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute("UPDATE repository_meta SET schema_version=8 WHERE singleton=1")
        connection.execute("PRAGMA user_version=8")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def validate_v8_invariants(connection: sqlite3.Connection) -> None:
    """Check immutable hierarchy and non-overlapping active allocation facts."""
    from finjuice.pipeline.reconcile.canonical import validate_reconcile

    validate_reconcile(connection)
