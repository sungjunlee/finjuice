"""Immutable canonical monthly close revisions and explicit reopen lineage."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from finjuice.pipeline.storage.sqlite.errors import RepositoryVersionError

TABLE_KEYS = {
    "close_revisions": ("close_id",),
    "close_reopenings": ("reopen_id",),
}

_SCHEMA = """
CREATE TABLE close_revisions (
 close_id TEXT PRIMARY KEY NOT NULL,
 period TEXT NOT NULL CHECK(length(period)=7 AND substr(period,5,1)='-'),
 close_revision INTEGER NOT NULL CHECK(typeof(close_revision)='integer' AND close_revision>=1),
 predecessor_close_id TEXT REFERENCES close_revisions(close_id),
 dataset_revision INTEGER NOT NULL CHECK(typeof(dataset_revision)='integer'
 AND dataset_revision>=0),
 rules_identity TEXT NOT NULL CHECK(length(rules_identity)>0),
 config_identity_json TEXT NOT NULL CHECK(length(config_identity_json)>1),
 calculation_policy TEXT NOT NULL CHECK(length(calculation_policy)>0),
 asset_scope TEXT NOT NULL CHECK(asset_scope IN
 ('transactions_only','transactions_and_asset_snapshots')),
 source_as_of TEXT NOT NULL CHECK(length(source_as_of)>0),
 completeness TEXT NOT NULL CHECK(completeness IN ('complete','incomplete')),
 unresolved_json TEXT NOT NULL CHECK(length(unresolved_json)>1),
 totals_json TEXT NOT NULL CHECK(length(totals_json)>1),
 report_json TEXT NOT NULL CHECK(length(report_json)>1),
 report_digest TEXT NOT NULL CHECK(length(report_digest)=64
 AND report_digest NOT GLOB '*[^0-9a-f]*'),
 diff_json TEXT NOT NULL CHECK(length(diff_json)>1),
 closed_at TEXT NOT NULL CHECK(length(closed_at)>0),
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
 DEFERRABLE INITIALLY DEFERRED,
 UNIQUE(period, close_revision),
 CHECK(close_id <> coalesce(predecessor_close_id,'')),
 CHECK((close_revision=1 AND predecessor_close_id IS NULL)
 OR (close_revision>1 AND predecessor_close_id IS NOT NULL))
);
CREATE TABLE close_reopenings (
 reopen_id TEXT PRIMARY KEY NOT NULL,
 close_id TEXT NOT NULL UNIQUE REFERENCES close_revisions(close_id),
 reason TEXT NOT NULL CHECK(length(reason)>0),
 reopened_at TEXT NOT NULL CHECK(length(reopened_at)>0),
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
 DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX idx_close_revisions_period ON close_revisions(period, close_revision);
"""


def apply_schema_v9(connection: sqlite3.Connection) -> None:
    """Add empty immutable close revision tables; never infer a close during upgrade."""
    if connection.execute("PRAGMA user_version").fetchone()[0] != 8:
        raise RepositoryVersionError("Schema v9 requires schema v8.")
    triggers = []
    for table, keys in TABLE_KEYS.items():
        predicate = " AND ".join(f"{key}=NEW.{key}" for key in keys)
        for action in ("UPDATE", "DELETE"):
            triggers.append(
                f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'immutable close revision'); END;"
            )
        triggers.append(
            f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
            f"WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) "
            "BEGIN SELECT RAISE(ABORT,'immutable close revision'); END;"
        )
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\n".join(triggers))
        connection.execute(
            "INSERT INTO schema_migrations VALUES (9, 'canonical_close', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute("UPDATE repository_meta SET schema_version=9 WHERE singleton=1")
        connection.execute("PRAGMA user_version=9")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def validate_v9_invariants(connection: sqlite3.Connection) -> None:
    """Check contiguous close lineage and single-successor reopen history."""
    from finjuice.pipeline.close.canonical import validate_close

    validate_close(connection)
