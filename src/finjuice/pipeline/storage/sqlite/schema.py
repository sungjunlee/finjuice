"""SQLite schema identity, creation, side-effect-free inspection, and upgrades."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from finjuice.pipeline.storage.sqlite.errors import (
    ObjectStoreError,
    RepositoryIntegrityError,
    RepositoryPathError,
    RepositoryVersionError,
)
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id, validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore, _mkdir_checked
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.snapshot import inspection_snapshot

SQLITE_APPLICATION_ID: Final = 0x464A5353  # "FJSS"
SQLITE_SCHEMA_VERSION: Final = 1
_BUSY_TIMEOUT_MS: Final = 5_000

_UUID_CHECK = """
    length({column}) = 36
    AND substr({column}, 9, 1) = '-'
    AND substr({column}, 14, 1) = '-'
    AND substr({column}, 19, 1) = '-'
    AND substr({column}, 24, 1) = '-'
    AND lower({column}) = {column}
    AND length(replace({column}, '-', '')) = 32
    AND replace({column}, '-', '') NOT GLOB '*[^0-9a-f]*'
"""


def _uuid_check(column: str) -> str:
    return _UUID_CHECK.format(column=column).strip()


@dataclass(frozen=True)
class RepositoryInfo:
    """Validated SQLite application and dataset identity."""

    application_id: int
    schema_version: int
    dataset_generation: str | None
    dataset_revision: int | None


def _schema_sql() -> str:
    uuid_entity = _uuid_check("entity_id")
    uuid_value = _uuid_check("value_id")
    uuid_provenance = _uuid_check("provenance_id")
    return f"""
CREATE TABLE repository_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    application_id INTEGER NOT NULL CHECK (application_id = {SQLITE_APPLICATION_ID}),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    dataset_generation TEXT NOT NULL CHECK ({_uuid_check("dataset_generation")}),
    dataset_revision INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(dataset_revision) = 'integer' AND dataset_revision >= 0)
);

CREATE TABLE schema_migrations (
    schema_version INTEGER PRIMARY KEY CHECK (schema_version >= 1),
    migration_name TEXT NOT NULL UNIQUE CHECK (length(migration_name) > 0),
    applied_at TEXT NOT NULL CHECK (length(applied_at) > 0)
);

CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_entity}),
    entity_kind TEXT NOT NULL CHECK (entity_kind IN (
        'source_occurrence', 'party', 'account', 'resource', 'observation',
        'config_revision', 'transaction', 'overview_fact', 'overview_balance',
        'overview_cashflow', 'overview_insurance', 'overview_investment',
        'overview_loan', 'asset_snapshot'
    )),
    UNIQUE (entity_id, entity_kind)
);

CREATE TABLE migration_identities (
    entity_id TEXT PRIMARY KEY NOT NULL,
    capture_manifest_digest TEXT NOT NULL
        CHECK (length(capture_manifest_digest) = 64
            AND capture_manifest_digest NOT GLOB '*[^0-9a-f]*'),
    record_kind TEXT NOT NULL,
    canonical_locator_json TEXT NOT NULL CHECK (length(canonical_locator_json) > 1),
    FOREIGN KEY (entity_id, record_kind) REFERENCES entities(entity_id, entity_kind),
    CHECK (substr(entity_id, 15, 1) = '5')
);

CREATE TABLE source_artifacts (
    source_artifact_id TEXT PRIMARY KEY NOT NULL
        CHECK (
            typeof(source_artifact_id) = 'text'
            AND length(source_artifact_id) = 71
            AND substr(source_artifact_id, 1, 7) = 'sha256:'
            AND substr(source_artifact_id, 8) NOT GLOB '*[^0-9a-f]*'
        ),
    digest_hex TEXT NOT NULL UNIQUE
        CHECK (length(digest_hex) = 64 AND digest_hex NOT GLOB '*[^0-9a-f]*'),
    byte_length INTEGER NOT NULL
        CHECK (typeof(byte_length) = 'integer' AND byte_length >= 0),
    object_path TEXT NOT NULL UNIQUE
        CHECK (
            object_path = 'objects/sha256/' || substr(digest_hex, 1, 2) || '/' || digest_hex
        ),
    CHECK (source_artifact_id = 'sha256:' || digest_hex)
);

CREATE TABLE source_occurrences (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'source_occurrence'
        CHECK (entity_kind = 'source_occurrence'),
    source_artifact_id TEXT NOT NULL REFERENCES source_artifacts(source_artifact_id),
    occurrence_kind TEXT NOT NULL CHECK (length(occurrence_kind) > 0),
    original_filename TEXT,
    imported_at TEXT,
    parser_version TEXT,
    source_schema_version TEXT,
    legacy_path TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE record_provenance (
    provenance_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_provenance}),
    source_occurrence_id TEXT NOT NULL REFERENCES source_occurrences(entity_id),
    source_coordinate_json TEXT NOT NULL CHECK (length(source_coordinate_json) > 1),
    legacy_locator_json TEXT NOT NULL CHECK (length(legacy_locator_json) > 1),
    parser_version TEXT,
    source_schema_version TEXT,
    UNIQUE (source_occurrence_id, legacy_locator_json)
);

CREATE TABLE exact_values (
    value_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_value}),
    value_kind TEXT NOT NULL CHECK (value_kind IN ('money', 'quantity', 'rate', 'number')),
    coefficient TEXT NOT NULL CHECK (
        typeof(coefficient) = 'text'
        AND (
            coefficient = '0'
            OR (
                substr(coefficient, 1, 1) BETWEEN '1' AND '9'
                AND coefficient NOT GLOB '*[^0-9]*'
            )
            OR (
                substr(coefficient, 1, 1) = '-'
                AND substr(coefficient, 2, 1) BETWEEN '1' AND '9'
                AND substr(coefficient, 2) NOT GLOB '*[^0-9]*'
            )
        )
    ),
    scale INTEGER NOT NULL CHECK (typeof(scale) = 'integer' AND scale BETWEEN 0 AND 255),
    lexical TEXT,
    origin_kind TEXT NOT NULL CHECK (origin_kind IN ('source', 'migration', 'calculated')),
    provenance_id TEXT REFERENCES record_provenance(provenance_id),
    CHECK (origin_kind = 'calculated' OR lexical IS NOT NULL),
    UNIQUE (value_id, value_kind)
);

CREATE TABLE money_values (
    value_id TEXT PRIMARY KEY NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'money' CHECK (value_kind = 'money'),
    currency_code TEXT,
    currency_unknown INTEGER NOT NULL DEFAULT 0 CHECK (currency_unknown IN (0, 1)),
    FOREIGN KEY (value_id, value_kind) REFERENCES exact_values(value_id, value_kind),
    CHECK (
        (currency_unknown = 1 AND currency_code IS NULL)
        OR (
            currency_unknown = 0
            AND currency_code IS NOT NULL
            AND length(currency_code) = 3
            AND currency_code = upper(currency_code)
            AND currency_code NOT GLOB '*[^A-Z]*'
        )
    )
);

CREATE TABLE quantity_values (
    value_id TEXT PRIMARY KEY NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'quantity' CHECK (value_kind = 'quantity'),
    unit TEXT NOT NULL CHECK (length(unit) > 3 AND instr(unit, '.v') > 1),
    FOREIGN KEY (value_id, value_kind) REFERENCES exact_values(value_id, value_kind)
);

CREATE TABLE rate_values (
    value_id TEXT PRIMARY KEY NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'rate' CHECK (value_kind = 'rate'),
    unit TEXT NOT NULL CHECK (length(unit) > 3 AND instr(unit, '.v') > 1),
    FOREIGN KEY (value_id, value_kind) REFERENCES exact_values(value_id, value_kind)
);

CREATE TABLE number_values (
    value_id TEXT PRIMARY KEY NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'number' CHECK (value_kind = 'number'),
    unit TEXT NOT NULL CHECK (length(unit) > 3 AND instr(unit, '.v') > 1),
    FOREIGN KEY (value_id, value_kind) REFERENCES exact_values(value_id, value_kind)
);

CREATE TABLE parties (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'party' CHECK (entity_kind = 'party'),
    party_kind TEXT NOT NULL CHECK (party_kind IN (
        'unknown', 'person', 'organization', 'household'
    )),
    display_name TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE accounts (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'account' CHECK (entity_kind = 'account'),
    account_kind TEXT NOT NULL CHECK (length(account_kind) > 0),
    display_name TEXT,
    ownership_state TEXT NOT NULL CHECK (ownership_state IN ('unknown', 'asserted')),
    owner_party_id TEXT REFERENCES parties(entity_id),
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind),
    CHECK (
        (ownership_state = 'unknown' AND owner_party_id IS NULL)
        OR (ownership_state = 'asserted' AND owner_party_id IS NOT NULL)
    )
);

CREATE TABLE resources (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'resource' CHECK (entity_kind = 'resource'),
    resource_kind TEXT NOT NULL CHECK (length(resource_kind) > 0),
    display_name TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE observations (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'observation' CHECK (entity_kind = 'observation'),
    source_occurrence_id TEXT NOT NULL REFERENCES source_occurrences(entity_id),
    observed_at TEXT,
    effective_at TEXT,
    collected_at TEXT,
    scope_state TEXT NOT NULL CHECK (scope_state IN ('complete', 'partial', 'unknown')),
    confirmation_state TEXT NOT NULL
        CHECK (confirmation_state IN ('unconfirmed', 'confirmed', 'rejected')),
    supersedes_observation_id TEXT REFERENCES observations(entity_id),
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind),
    CHECK (supersedes_observation_id IS NULL OR supersedes_observation_id != entity_id)
);

CREATE TABLE config_revisions (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'config_revision' CHECK (entity_kind = 'config_revision'),
    config_kind TEXT NOT NULL
        CHECK (config_kind IN ('rules', 'goals', 'assets', 'scenarios', 'schema', 'other')),
    source_artifact_id TEXT NOT NULL REFERENCES source_artifacts(source_artifact_id),
    source_occurrence_id TEXT NOT NULL REFERENCES source_occurrences(entity_id),
    parsed_status TEXT NOT NULL CHECK (parsed_status IN ('parsed', 'invalid', 'opaque')),
    parser_version TEXT,
    canonical_payload_json TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind),
    UNIQUE (config_kind, source_occurrence_id)
);

CREATE TABLE legacy_payloads (
    payload_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("payload_id")}),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 1)
);

CREATE TABLE preservation_issues (
    issue_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("issue_id")}),
    provenance_id TEXT NOT NULL REFERENCES record_provenance(provenance_id),
    field_name TEXT,
    issue_kind TEXT NOT NULL CHECK (length(issue_kind) > 0),
    lexical_value TEXT,
    detail_json TEXT NOT NULL CHECK (length(detail_json) > 1)
);

CREATE TABLE migration_dispositions (
    provenance_id TEXT PRIMARY KEY NOT NULL REFERENCES record_provenance(provenance_id),
    disposition TEXT NOT NULL CHECK (disposition IN (
        'migrated', 'preserved_opaque', 'quarantined', 'intentionally_absent'
    )),
    reason TEXT NOT NULL CHECK (length(reason) > 0)
);

CREATE TABLE legacy_identifiers (
    mapping_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("mapping_id")}),
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    identifier_kind TEXT NOT NULL CHECK (identifier_kind IN (
        'row_hash', 'file_id', 'source_row', 'old_path', 'account_text', 'fact_id', 'other'
    )),
    identifier_value TEXT NOT NULL,
    provenance_id TEXT REFERENCES record_provenance(provenance_id),
    capture_manifest_digest TEXT NOT NULL
        CHECK (length(capture_manifest_digest) = 64
            AND capture_manifest_digest NOT GLOB '*[^0-9a-f]*'),
    UNIQUE (entity_id, identifier_kind, identifier_value, provenance_id)
);

CREATE TABLE legacy_identifier_supersessions (
    supersession_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("supersession_id")}),
    previous_mapping_id TEXT NOT NULL UNIQUE REFERENCES legacy_identifiers(mapping_id),
    replacement_mapping_id TEXT NOT NULL REFERENCES legacy_identifiers(mapping_id),
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    CHECK (previous_mapping_id != replacement_mapping_id)
);

CREATE TABLE transactions (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'transaction' CHECK (entity_kind = 'transaction'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    account_id TEXT NOT NULL REFERENCES accounts(entity_id),
    amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
    date_raw TEXT NOT NULL,
    time_raw TEXT NOT NULL,
    datetime_raw TEXT NOT NULL,
    timezone_state TEXT NOT NULL CHECK (timezone_state IN ('known', 'unknown')),
    type_raw TEXT,
    type_norm TEXT NOT NULL CHECK (type_norm IN ('expense', 'income', 'transfer', 'other')),
    major_raw TEXT,
    minor_raw TEXT,
    merchant_raw TEXT,
    memo_raw TEXT,
    notes_manual TEXT,
    account_text TEXT NOT NULL,
    counterparty TEXT,
    category_rule TEXT,
    category_manual TEXT,
    category_final TEXT,
    tags_rule_json TEXT NOT NULL,
    tags_ai_json TEXT NOT NULL,
    tags_manual_json TEXT NOT NULL,
    tags_final_json TEXT NOT NULL,
    confidence_value_id TEXT REFERENCES number_values(value_id),
    needs_review INTEGER CHECK (needs_review IS NULL OR needs_review IN (0, 1)),
    is_transfer_candidate INTEGER
        CHECK (is_transfer_candidate IS NULL OR is_transfer_candidate IN (0, 1)),
    is_transfer INTEGER CHECK (is_transfer IS NULL OR is_transfer IN (0, 1)),
    transfer_group_id TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE overview_facts (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_fact' CHECK (entity_kind = 'overview_fact'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    snapshot_date TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    block_id TEXT NOT NULL,
    block_title TEXT NOT NULL,
    fact_kind TEXT NOT NULL,
    row_label TEXT,
    column_label TEXT,
    numeric_value_id TEXT REFERENCES exact_values(value_id),
    value_text TEXT,
    value_type TEXT NOT NULL
        CHECK (value_type IN ('number', 'text', 'date', 'empty', 'unsupported')),
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind),
    CHECK ((value_type = 'number') = (numeric_value_id IS NOT NULL)),
    CHECK (value_type IN ('number', 'empty') OR value_text IS NOT NULL)
);

CREATE TABLE overview_balances (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_balance' CHECK (entity_kind = 'overview_balance'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    source_fact_id TEXT NOT NULL REFERENCES overview_facts(entity_id),
    amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
    snapshot_date TEXT NOT NULL,
    side TEXT NOT NULL,
    category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE overview_cashflows (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_cashflow' CHECK (entity_kind = 'overview_cashflow'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    source_fact_id TEXT NOT NULL REFERENCES overview_facts(entity_id),
    amount_value_id TEXT NOT NULL REFERENCES money_values(value_id),
    snapshot_date TEXT NOT NULL,
    period_month TEXT NOT NULL,
    category TEXT NOT NULL,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE overview_insurance (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_insurance'
        CHECK (entity_kind = 'overview_insurance'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    source_fact_id TEXT NOT NULL REFERENCES overview_facts(entity_id),
    paid_amount_value_id TEXT REFERENCES money_values(value_id),
    snapshot_date TEXT NOT NULL,
    institution TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    contract_status TEXT,
    contract_date TEXT,
    maturity_date TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE overview_investments (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_investment'
        CHECK (entity_kind = 'overview_investment'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    source_fact_id TEXT NOT NULL REFERENCES overview_facts(entity_id),
    principal_value_id TEXT REFERENCES money_values(value_id),
    valuation_value_id TEXT REFERENCES money_values(value_id),
    return_rate_value_id TEXT REFERENCES rate_values(value_id),
    snapshot_date TEXT NOT NULL,
    product_type TEXT,
    institution TEXT NOT NULL,
    product_name TEXT NOT NULL,
    start_date TEXT,
    maturity_date TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE overview_loans (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'overview_loan' CHECK (entity_kind = 'overview_loan'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    source_fact_id TEXT NOT NULL REFERENCES overview_facts(entity_id),
    principal_value_id TEXT REFERENCES money_values(value_id),
    balance_value_id TEXT REFERENCES money_values(value_id),
    interest_rate_value_id TEXT REFERENCES rate_values(value_id),
    snapshot_date TEXT NOT NULL,
    loan_type TEXT,
    institution TEXT NOT NULL,
    product_name TEXT NOT NULL,
    start_date TEXT,
    maturity_date TEXT,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind)
);

CREATE TABLE asset_snapshots (
    entity_id TEXT PRIMARY KEY NOT NULL,
    entity_kind TEXT NOT NULL DEFAULT 'asset_snapshot' CHECK (entity_kind = 'asset_snapshot'),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    account_id TEXT NOT NULL REFERENCES accounts(entity_id),
    resource_id TEXT NOT NULL REFERENCES resources(entity_id),
    quantity_value_id TEXT REFERENCES quantity_values(value_id),
    market_value_id TEXT REFERENCES money_values(value_id),
    snapshot_date TEXT NOT NULL,
    FOREIGN KEY (entity_id, entity_kind) REFERENCES entities(entity_id, entity_kind),
    CHECK (quantity_value_id IS NOT NULL OR market_value_id IS NOT NULL)
);

CREATE INDEX idx_legacy_identifier_lookup
    ON legacy_identifiers(identifier_kind, identifier_value);
CREATE UNIQUE INDEX uq_legacy_identifier_identity
    ON legacy_identifiers(
        entity_id,
        identifier_kind,
        identifier_value,
        coalesce(provenance_id, '')
    );
CREATE INDEX idx_source_occurrence_artifact
    ON source_occurrences(source_artifact_id);
CREATE INDEX idx_transaction_observation
    ON transactions(observation_id);
CREATE INDEX idx_observation_effective
    ON observations(effective_at, collected_at);
"""


_IMMUTABLE_TABLES = (
    "schema_migrations",
    "entities",
    "migration_identities",
    "source_artifacts",
    "source_occurrences",
    "record_provenance",
    "exact_values",
    "money_values",
    "quantity_values",
    "rate_values",
    "number_values",
    "config_revisions",
    "legacy_payloads",
    "preservation_issues",
    "migration_dispositions",
    "legacy_identifiers",
    "legacy_identifier_supersessions",
)

_ENTITY_SUBTYPE_CHECKS: Final = (
    "SELECT entity_id FROM entities WHERE entity_kind = 'source_occurrence' "
    "EXCEPT SELECT entity_id FROM source_occurrences",
    "SELECT entity_id FROM entities WHERE entity_kind = 'party' "
    "EXCEPT SELECT entity_id FROM parties",
    "SELECT entity_id FROM entities WHERE entity_kind = 'account' "
    "EXCEPT SELECT entity_id FROM accounts",
    "SELECT entity_id FROM entities WHERE entity_kind = 'resource' "
    "EXCEPT SELECT entity_id FROM resources",
    "SELECT entity_id FROM entities WHERE entity_kind = 'observation' "
    "EXCEPT SELECT entity_id FROM observations",
    "SELECT entity_id FROM entities WHERE entity_kind = 'config_revision' "
    "EXCEPT SELECT entity_id FROM config_revisions",
    "SELECT entity_id FROM entities WHERE entity_kind = 'transaction' "
    "EXCEPT SELECT entity_id FROM transactions",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_fact' "
    "EXCEPT SELECT entity_id FROM overview_facts",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_balance' "
    "EXCEPT SELECT entity_id FROM overview_balances",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_cashflow' "
    "EXCEPT SELECT entity_id FROM overview_cashflows",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_insurance' "
    "EXCEPT SELECT entity_id FROM overview_insurance",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_investment' "
    "EXCEPT SELECT entity_id FROM overview_investments",
    "SELECT entity_id FROM entities WHERE entity_kind = 'overview_loan' "
    "EXCEPT SELECT entity_id FROM overview_loans",
    "SELECT entity_id FROM entities WHERE entity_kind = 'asset_snapshot' "
    "EXCEPT SELECT entity_id FROM asset_snapshots",
)

_EXACT_SUBTYPE_CHECKS: Final = (
    "SELECT value_id FROM exact_values WHERE value_kind = 'money' "
    "EXCEPT SELECT value_id FROM money_values",
    "SELECT value_id FROM exact_values WHERE value_kind = 'quantity' "
    "EXCEPT SELECT value_id FROM quantity_values",
    "SELECT value_id FROM exact_values WHERE value_kind = 'rate' "
    "EXCEPT SELECT value_id FROM rate_values",
    "SELECT value_id FROM exact_values WHERE value_kind = 'number' "
    "EXCEPT SELECT value_id FROM number_values",
)

_SOURCE_BINDING_CHECKS: Final = (
    (
        "WITH typed_records(entity_id, observation_id, provenance_id) AS ("
        "SELECT entity_id, observation_id, provenance_id FROM transactions UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_facts UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_balances UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_cashflows UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_insurance UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_investments UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM overview_loans UNION ALL "
        "SELECT entity_id, observation_id, provenance_id FROM asset_snapshots) "
        "SELECT record.entity_id FROM typed_records AS record "
        "JOIN observations AS observation ON observation.entity_id = record.observation_id "
        "JOIN record_provenance AS provenance "
        "ON provenance.provenance_id = record.provenance_id "
        "WHERE observation.source_occurrence_id <> provenance.source_occurrence_id",
        "A typed record joins evidence from different source occurrences.",
    ),
    (
        "SELECT revision.entity_id FROM config_revisions AS revision "
        "JOIN source_occurrences AS occurrence "
        "ON occurrence.entity_id = revision.source_occurrence_id "
        "WHERE occurrence.source_artifact_id <> revision.source_artifact_id",
        "A config revision artifact does not match its source occurrence.",
    ),
    (
        "WITH projections(entity_id, source_fact_id, provenance_id) AS ("
        "SELECT entity_id, source_fact_id, provenance_id FROM overview_balances UNION ALL "
        "SELECT entity_id, source_fact_id, provenance_id FROM overview_cashflows UNION ALL "
        "SELECT entity_id, source_fact_id, provenance_id FROM overview_insurance UNION ALL "
        "SELECT entity_id, source_fact_id, provenance_id FROM overview_investments UNION ALL "
        "SELECT entity_id, source_fact_id, provenance_id FROM overview_loans) "
        "SELECT projection.entity_id FROM projections AS projection "
        "JOIN record_provenance AS projection_provenance "
        "ON projection_provenance.provenance_id = projection.provenance_id "
        "JOIN overview_facts AS fact ON fact.entity_id = projection.source_fact_id "
        "JOIN record_provenance AS fact_provenance "
        "ON fact_provenance.provenance_id = fact.provenance_id "
        "WHERE projection_provenance.source_occurrence_id "
        "<> fact_provenance.source_occurrence_id",
        "An overview projection and its source fact come from different occurrences.",
    ),
    (
        "SELECT value_id FROM exact_values "
        "WHERE origin_kind IN ('source', 'migration') AND provenance_id IS NULL",
        "A source or migration exact value is missing provenance.",
    ),
    (
        "WITH typed_values(entity_id, value_id, provenance_id) AS ("
        "SELECT entity_id, amount_value_id, provenance_id FROM transactions UNION ALL "
        "SELECT entity_id, confidence_value_id, provenance_id FROM transactions UNION ALL "
        "SELECT entity_id, numeric_value_id, provenance_id FROM overview_facts UNION ALL "
        "SELECT entity_id, amount_value_id, provenance_id FROM overview_balances UNION ALL "
        "SELECT entity_id, amount_value_id, provenance_id FROM overview_cashflows UNION ALL "
        "SELECT entity_id, paid_amount_value_id, provenance_id FROM overview_insurance UNION ALL "
        "SELECT entity_id, principal_value_id, provenance_id FROM overview_investments UNION ALL "
        "SELECT entity_id, valuation_value_id, provenance_id FROM overview_investments UNION ALL "
        "SELECT entity_id, return_rate_value_id, provenance_id FROM overview_investments UNION ALL "
        "SELECT entity_id, principal_value_id, provenance_id FROM overview_loans UNION ALL "
        "SELECT entity_id, balance_value_id, provenance_id FROM overview_loans UNION ALL "
        "SELECT entity_id, interest_rate_value_id, provenance_id FROM overview_loans UNION ALL "
        "SELECT entity_id, quantity_value_id, provenance_id FROM asset_snapshots UNION ALL "
        "SELECT entity_id, market_value_id, provenance_id FROM asset_snapshots) "
        "SELECT record.entity_id FROM typed_values AS record "
        "JOIN exact_values AS value ON value.value_id = record.value_id "
        "JOIN record_provenance AS record_provenance "
        "ON record_provenance.provenance_id = record.provenance_id "
        "JOIN record_provenance AS value_provenance "
        "ON value_provenance.provenance_id = value.provenance_id "
        "WHERE value.origin_kind IN ('source', 'migration') "
        "AND record_provenance.source_occurrence_id "
        "<> value_provenance.source_occurrence_id",
        "A typed record and its exact value come from different source occurrences.",
    ),
)


def _immutable_trigger_sql() -> str:
    statements: list[str] = []
    for table in _IMMUTABLE_TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
            )
        )
    statements.extend(
        (
            "CREATE TRIGGER repository_meta_guarded_update "
            "BEFORE UPDATE ON repository_meta WHEN "
            "NEW.application_id <> OLD.application_id "
            "OR NEW.dataset_generation <> OLD.dataset_generation "
            "OR NEW.schema_version < OLD.schema_version "
            "OR NEW.dataset_revision < OLD.dataset_revision "
            "BEGIN SELECT RAISE(ABORT, 'protected repository metadata'); END;",
            "CREATE TRIGGER repository_meta_no_delete BEFORE DELETE ON repository_meta "
            "BEGIN SELECT RAISE(ABORT, 'protected repository metadata'); END;",
            "CREATE TRIGGER repository_meta_no_reinsert BEFORE INSERT ON repository_meta "
            "WHEN EXISTS (SELECT 1 FROM repository_meta) "
            "BEGIN SELECT RAISE(ABORT, 'protected repository metadata'); END;",
        )
    )
    return "\n".join(statements)


def initialize_repository(paths: GenerationPaths, dataset_generation: str) -> RepositoryInfo:
    """Build schema v1 in staging, verify it, and publish a new candidate database."""
    validate_entity_id(dataset_generation)
    _prepare_generation_layout(paths)
    if paths.database.exists() or paths.database.is_symlink():
        raise RepositoryPathError("Repository database already exists and will not be replaced.")
    staging = paths.root / f".finjuice-sqlite-staging-{uuid.uuid4().hex}"
    connection = _connect_builder(staging)
    try:
        _apply_schema_v1(connection, dataset_generation)
        info = _validate_connection(
            connection,
            expected_generation=dataset_generation,
            object_paths=paths,
        )
    except Exception:
        connection.close()
        _cleanup_staging(staging)
        raise
    connection.close()
    _publish_database(staging, paths.database)
    return info


def inspect_repository(
    database: Path,
    *,
    scratch_root: Path | None = None,
) -> RepositoryInfo:
    """Inspect the latest stable DB/WAL state without SQLite-opening the original files."""
    with inspection_snapshot(database, scratch_root=scratch_root) as snapshot:
        connection = _connect_snapshot(snapshot)
        try:
            return _read_info(connection)
        finally:
            connection.close()


def upgrade_repository(
    source: Path,
    destination: GenerationPaths,
    *,
    scratch_root: Path | None = None,
) -> RepositoryInfo:
    """Copy a stable DB plus referenced objects into a separately published candidate."""
    _prepare_generation_layout(destination)
    if destination.database.exists() or destination.database.is_symlink():
        raise RepositoryPathError("Upgrade destination already exists and will not be replaced.")

    with inspection_snapshot(source, scratch_root=scratch_root) as snapshot:
        source_connection = _connect_snapshot(snapshot)
        try:
            source_info = _read_info(source_connection)
            if source_info.schema_version > SQLITE_SCHEMA_VERSION:
                raise RepositoryVersionError(
                    f"SQLite schema v{source_info.schema_version} is newer than supported "
                    f"v{SQLITE_SCHEMA_VERSION}."
                )
            if source_info.schema_version != SQLITE_SCHEMA_VERSION:
                raise RepositoryVersionError(
                    f"SQLite schema v{source_info.schema_version} has no supported upgrade path."
                )
            staging = destination.root / f".finjuice-sqlite-staging-{uuid.uuid4().hex}"
            target_connection = _connect_builder(staging)
            try:
                source_connection.backup(target_connection)
                _normalize_journal_mode(target_connection)
                info = _validate_connection(target_connection)
                _copy_source_objects(source, source_connection, destination)
                info = _validate_connection(target_connection, object_paths=destination)
            except Exception:
                target_connection.close()
                _cleanup_staging(staging)
                raise
            target_connection.close()
        finally:
            source_connection.close()
    _publish_database(staging, destination.database)
    return info


def _copy_source_objects(
    source_database: Path,
    source_connection: sqlite3.Connection,
    destination: GenerationPaths,
) -> None:
    """Verify and carry every DB-referenced object into an upgrade candidate."""
    rows = source_connection.execute(
        "SELECT source_artifact_id, byte_length FROM source_artifacts ORDER BY source_artifact_id"
    ).fetchall()
    source_paths = GenerationPaths(source_database.expanduser().absolute().parent)
    source_store = SourceObjectStore(source_paths)
    destination_store = SourceObjectStore(destination)
    for artifact_id, byte_length in rows:
        try:
            source_artifact = source_store.verify(str(artifact_id), int(byte_length))
        except (ObjectStoreError, RepositoryPathError) as exc:
            raise RepositoryIntegrityError(
                "A referenced immutable source object is missing, mutable, or corrupt."
            ) from exc
        copied = destination_store.publish_path(source_paths.root / source_artifact.relative_path)
        if copied.artifact_id != artifact_id or copied.byte_length != byte_length:
            raise RepositoryIntegrityError(
                "Upgrade source object changed while the candidate was built."
            )


def validate_repository(
    database: Path,
    *,
    scratch_root: Path | None = None,
) -> RepositoryInfo:
    """Run version, integrity, and foreign-key checks on a non-mutating snapshot."""
    with inspection_snapshot(database, scratch_root=scratch_root) as snapshot:
        connection = _connect_snapshot(snapshot)
        try:
            repository_paths = GenerationPaths(database.expanduser().absolute().parent)
            return _validate_connection(connection, object_paths=repository_paths)
        finally:
            connection.close()


def _apply_schema_v1(
    connection: sqlite3.Connection,
    dataset_generation: str,
    dataset_revision: int = 0,
) -> None:
    if isinstance(dataset_revision, bool) or not isinstance(dataset_revision, int):
        raise RepositoryIntegrityError("Dataset revision must be an integer.")
    if dataset_revision < 0:
        raise RepositoryIntegrityError("Dataset revision must be non-negative.")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 0:
        raise RepositoryVersionError("Schema v1 can only initialize a bootstrap database.")
    connection.executescript("BEGIN IMMEDIATE;\n" + _schema_sql() + _immutable_trigger_sql())
    try:
        connection.execute(
            "INSERT INTO repository_meta "
            "(singleton, application_id, schema_version, dataset_generation, dataset_revision) "
            "VALUES (1, ?, ?, ?, ?)",
            (
                SQLITE_APPLICATION_ID,
                SQLITE_SCHEMA_VERSION,
                dataset_generation,
                dataset_revision,
            ),
        )
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (?, ?, ?)",
            (
                SQLITE_SCHEMA_VERSION,
                "initial_authoritative_storage",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
        connection.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION}")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _connect_builder(path: Path) -> sqlite3.Connection:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        file_descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(file_descriptor, 0o600)
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise RepositoryPathError(
            "Repository staging database could not be created safely."
        ) from exc
    connection = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    return connection


def _normalize_journal_mode(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
    if row is None or str(row[0]).lower() != "delete":
        raise RepositoryIntegrityError("Upgrade candidate journal mode could not be normalized.")


def _connect_snapshot(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _read_info(connection: sqlite3.Connection) -> RepositoryInfo:
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != SQLITE_APPLICATION_ID:
        raise RepositoryVersionError("SQLite file is not a finjuice authoritative repository.")
    if schema_version != SQLITE_SCHEMA_VERSION:
        relation = "newer than" if schema_version > SQLITE_SCHEMA_VERSION else "unsupported by"
        raise RepositoryVersionError(
            f"SQLite schema v{schema_version} is {relation} this build "
            f"(supported v{SQLITE_SCHEMA_VERSION})."
        )
    try:
        row = connection.execute(
            "SELECT application_id, schema_version, dataset_generation, dataset_revision "
            "FROM repository_meta WHERE singleton = 1"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise RepositoryIntegrityError("Repository metadata could not be read.") from exc
    if row is None or int(row[0]) != application_id or int(row[1]) != schema_version:
        raise RepositoryIntegrityError("Repository metadata disagrees with SQLite header identity.")
    try:
        validate_entity_id(str(row[2]))
    except ValueError as exc:
        raise RepositoryIntegrityError("Dataset generation ID is invalid.") from exc
    return RepositoryInfo(application_id, schema_version, str(row[2]), int(row[3]))


def _validate_connection(
    connection: sqlite3.Connection,
    *,
    expected_generation: str | None = None,
    object_paths: GenerationPaths | None = None,
) -> RepositoryInfo:
    info = _read_info(connection)
    if expected_generation is not None and info.dataset_generation != expected_generation:
        raise RepositoryIntegrityError("Repository generation does not match the builder request.")
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise RepositoryIntegrityError("SQLite integrity_check failed.")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RepositoryIntegrityError("SQLite foreign_key_check failed.")
    _validate_application_invariants(connection)
    if object_paths is not None:
        _validate_source_objects(connection, object_paths)
    return info


def _validate_application_invariants(connection: sqlite3.Connection) -> None:
    for query in _ENTITY_SUBTYPE_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError("An entity is missing its matching typed row.")
    for query in _EXACT_SUBTYPE_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError("An exact value is missing its matching subtype row.")
    _validate_schema_migration_ledger(connection)
    _validate_source_bindings(connection)
    identities = connection.execute(
        "SELECT entity_id, capture_manifest_digest, record_kind, canonical_locator_json "
        "FROM migration_identities ORDER BY entity_id"
    ).fetchall()
    identity_ids = {str(row[0]) for row in identities}
    v5_entity_ids = {
        str(row[0])
        for row in connection.execute(
            "SELECT entity_id FROM entities WHERE substr(entity_id, 15, 1) = '5'"
        ).fetchall()
    }
    if identity_ids != v5_entity_ids:
        raise RepositoryIntegrityError(
            "Every UUIDv5 entity must have exactly one migration identity."
        )
    for entity_id, digest, record_kind, locator_json in identities:
        try:
            locator = json.loads(str(locator_json))
            derived_id = migration_entity_id(str(digest), str(record_kind), locator)
        except (TypeError, ValueError) as exc:
            raise RepositoryIntegrityError("A migration identity is invalid.") from exc
        if derived_id != entity_id:
            raise RepositoryIntegrityError("A migration identity does not re-derive its entity ID.")


def _validate_schema_migration_ledger(connection: sqlite3.Connection) -> None:
    """Require one immutable ledger row for every applied schema version."""
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    migration_versions = [
        int(row[0])
        for row in connection.execute(
            "SELECT schema_version FROM schema_migrations ORDER BY schema_version"
        ).fetchall()
    ]
    if migration_versions != list(range(1, schema_version + 1)):
        raise RepositoryIntegrityError(
            "The schema migration ledger does not match the current schema version."
        )


def _validate_source_bindings(connection: sqlite3.Connection) -> None:
    """Reject typed rows that combine evidence from different source occurrences."""
    for query, message in _SOURCE_BINDING_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError(message)


def _validate_source_objects(
    connection: sqlite3.Connection,
    paths: GenerationPaths,
) -> None:
    store = SourceObjectStore(paths)
    rows = connection.execute(
        "SELECT source_artifact_id, byte_length, object_path FROM source_artifacts "
        "ORDER BY source_artifact_id"
    ).fetchall()
    try:
        for artifact_id, byte_length, object_path in rows:
            verified = store.verify(str(artifact_id), int(byte_length))
            if verified.relative_path != str(object_path):
                raise RepositoryIntegrityError(
                    "Source artifact database path disagrees with its object identity."
                )
    except (ObjectStoreError, RepositoryPathError) as exc:
        raise RepositoryIntegrityError(
            "A referenced immutable source object is missing, mutable, or corrupt."
        ) from exc


def _prepare_generation_layout(paths: GenerationPaths) -> None:
    SourceObjectStore(paths).prepare()
    for directory in (paths.manifests, paths.derived):
        _mkdir_checked(directory, boundary=paths.root)


def _publish_database(staging: Path, destination: Path) -> None:
    linked_destination = False
    removed_staging = False
    try:
        staging_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)
        os.link(staging, destination, follow_symlinks=False)
        linked_destination = True
        _fsync_directory(destination.parent)
        staging.unlink()
        removed_staging = True
        _fsync_directory(destination.parent)
    except FileExistsError as exc:
        _cleanup_staging(staging)
        raise RepositoryPathError(
            "Repository database already exists and was not replaced."
        ) from exc
    except OSError as exc:
        if linked_destination and not removed_staging:
            try:
                destination.unlink(missing_ok=True)
                _fsync_directory(destination.parent)
            except OSError:
                pass
        _cleanup_staging(staging)
        raise RepositoryPathError("Repository database could not be published atomically.") from exc


def _cleanup_staging(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(f"{path}-journal").unlink(missing_ok=True)
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
