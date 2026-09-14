"""Immutable source-backed asset meanings; original observations remain unchanged."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from finjuice.pipeline.storage.sqlite.errors import RepositoryVersionError

_SCHEMA = """
CREATE TABLE asset_meaning_assertions (
 assertion_id TEXT PRIMARY KEY NOT NULL,
 source_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
 value_id TEXT NOT NULL REFERENCES exact_values(value_id),
 account_id TEXT NOT NULL REFERENCES accounts(entity_id),
 resource_id TEXT REFERENCES resources(entity_id),
 measure_kind TEXT NOT NULL CHECK(measure_kind IN
   ('balance','holding_quantity','valuation','cash_movement','right_obligation','expected_inflow')),
 source_kind TEXT NOT NULL CHECK(source_kind IN
   ('screenshot','institution_export','manual','workbook_summary','workbook_holdings')),
 as_of TEXT NOT NULL,
 scope_state TEXT NOT NULL CHECK(scope_state IN ('complete','partial','unknown')),
 confirmation_state TEXT NOT NULL
   CHECK(confirmation_state IN ('confirmed','unconfirmed','rejected')),
 original_currency TEXT,
 net_worth_sign INTEGER NOT NULL CHECK(net_worth_sign IN (-1,1)),
 fx_value_id TEXT REFERENCES rate_values(value_id),
 fx_quote_currency TEXT,
 fx_as_of TEXT,
 fx_evidence_json TEXT,
 evidence_json TEXT NOT NULL,
 supersedes_assertion_id TEXT UNIQUE REFERENCES asset_meaning_assertions(assertion_id),
 created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
   DEFERRABLE INITIALLY DEFERRED,
 CHECK(assertion_id <> coalesce(supersedes_assertion_id,'')),
 CHECK((fx_value_id IS NULL AND fx_quote_currency IS NULL AND fx_as_of IS NULL
   AND fx_evidence_json IS NULL) OR (fx_value_id IS NOT NULL AND fx_quote_currency IS NOT NULL
   AND fx_as_of IS NOT NULL AND fx_evidence_json IS NOT NULL))
);
CREATE INDEX asset_meaning_source ON asset_meaning_assertions(source_entity_id);
CREATE TRIGGER asset_meaning_no_update BEFORE UPDATE ON asset_meaning_assertions
BEGIN SELECT RAISE(ABORT, 'immutable asset meaning'); END;
CREATE TRIGGER asset_meaning_no_delete BEFORE DELETE ON asset_meaning_assertions
BEGIN SELECT RAISE(ABORT, 'immutable asset meaning'); END;
CREATE TRIGGER asset_meaning_no_replace BEFORE INSERT ON asset_meaning_assertions
WHEN EXISTS(SELECT 1 FROM asset_meaning_assertions WHERE assertion_id = NEW.assertion_id)
BEGIN SELECT RAISE(ABORT, 'immutable asset meaning'); END;
"""


def apply_schema_v7(connection: sqlite3.Connection) -> None:
    """Add empty asset meanings without confirming or interpreting captured source rows."""
    if connection.execute("PRAGMA user_version").fetchone()[0] != 6:
        raise RepositoryVersionError("Schema v7 requires a schema v6 repository.")
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (7, 'source_backed_asset_meanings', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.execute("UPDATE repository_meta SET schema_version = 7 WHERE singleton = 1")
        connection.execute("PRAGMA user_version = 7")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def validate_v7_invariants(connection: sqlite3.Connection) -> None:
    """Validate source/value linkage and immutable interpretation chains."""
    from finjuice.pipeline.storage.sqlite.asset_meanings import validate_asset_meanings

    validate_asset_meanings(connection)
