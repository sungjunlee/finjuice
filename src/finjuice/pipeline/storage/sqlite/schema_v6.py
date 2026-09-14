"""Typed, append-only runtime account source bindings, separate from migration mappings."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError, RepositoryVersionError
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

BINDING_TABLE = "account_source_bindings"
_SCHEMA = """
CREATE TABLE account_source_bindings (
 binding_id TEXT PRIMARY KEY NOT NULL,
 source_namespace TEXT NOT NULL CHECK(length(source_namespace) BETWEEN 1 AND 128),
 external_key TEXT NOT NULL CHECK(length(external_key) BETWEEN 1 AND 512),
 account_id TEXT NOT NULL REFERENCES accounts(entity_id),
 evidence_json TEXT NOT NULL CHECK(length(evidence_json) > 2),
 supersedes_binding_id TEXT UNIQUE REFERENCES account_source_bindings(binding_id),
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
    DEFERRABLE INITIALLY DEFERRED,
 CHECK(supersedes_binding_id IS NULL OR supersedes_binding_id <> binding_id)
);
CREATE INDEX account_source_binding_lookup
    ON account_source_bindings(source_namespace, external_key);
CREATE TRIGGER account_source_bindings_no_update BEFORE UPDATE ON account_source_bindings
BEGIN SELECT RAISE(ABORT, 'immutable account binding'); END;
CREATE TRIGGER account_source_bindings_no_delete BEFORE DELETE ON account_source_bindings
BEGIN SELECT RAISE(ABORT, 'immutable account binding'); END;
CREATE TRIGGER account_source_bindings_no_replace BEFORE INSERT ON account_source_bindings
WHEN EXISTS(SELECT 1 FROM account_source_bindings WHERE binding_id = NEW.binding_id)
BEGIN SELECT RAISE(ABORT, 'immutable account binding'); END;
"""


def apply_schema_v6(connection: sqlite3.Connection) -> None:
    """Add empty runtime binding assertions without interpreting legacy aliases."""
    if connection.execute("PRAGMA user_version").fetchone()[0] != 5:
        raise RepositoryVersionError("Schema v6 requires a schema v5 repository.")
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (6, 'runtime_account_source_bindings', ?)",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),),
        )
        connection.execute("UPDATE repository_meta SET schema_version = 6 WHERE singleton = 1")
        connection.execute("PRAGMA user_version = 6")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def validate_v6_invariants(connection: sqlite3.Connection) -> None:
    """Validate assertion identity, evidence and same-source acyclic correction chains."""
    rows = connection.execute(
        "SELECT binding_id, source_namespace, external_key, account_id, evidence_json, "
        "supersedes_binding_id FROM account_source_bindings"
    ).fetchall()
    by_id = {row[0]: row for row in rows}
    for row in rows:
        try:
            validate_entity_id(row[0])
            validate_entity_id(row[3])
            evidence = json.loads(row[4])
            if not isinstance(evidence, dict) or not evidence:
                raise ValueError
            seen = {row[0]}
            previous = row[5]
            while previous is not None:
                parent = by_id[previous]
                if previous in seen or parent[1:3] != row[1:3]:
                    raise ValueError
                seen.add(previous)
                previous = parent[5]
        except (ValueError, KeyError, TypeError) as exc:
            raise RepositoryIntegrityError(
                "Account source binding evidence is inconsistent."
            ) from exc
