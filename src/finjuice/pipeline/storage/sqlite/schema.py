"""SQLite schema identity, creation, side-effect-free inspection, and upgrades.

Application-invariant helpers live in
:mod:`finjuice.pipeline.storage.sqlite.schema_invariants` and are re-exported
here so existing callers can keep importing from this module.
"""

from __future__ import annotations

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
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore, _mkdir_checked
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _OWNERSHIP_SHARE_UNIT as _OWNERSHIP_SHARE_UNIT,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _is_canonical_calendar_date as _is_canonical_calendar_date,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _reject_json_constant as _reject_json_constant,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_application_invariants as _validate_application_invariants,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_intake_applications as _validate_intake_applications,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_ownership_assertions as _validate_ownership_assertions,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_relation_assertions as _validate_relation_assertions,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_source_objects as _validate_source_objects,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_v3_invariants as _validate_v3_invariants,
)
from finjuice.pipeline.storage.sqlite.schema_invariants import (
    _validate_v4_invariants as _validate_v4_invariants,
)
from finjuice.pipeline.storage.sqlite.schema_v5 import apply_schema_v5
from finjuice.pipeline.storage.sqlite.schema_v6 import apply_schema_v6
from finjuice.pipeline.storage.sqlite.schema_v7 import apply_schema_v7
from finjuice.pipeline.storage.sqlite.schema_v8 import apply_schema_v8
from finjuice.pipeline.storage.sqlite.schema_v9 import apply_schema_v9
from finjuice.pipeline.storage.sqlite.snapshot import inspection_snapshot

SQLITE_APPLICATION_ID: Final = 0x464A5353  # "FJSS"
SQLITE_SCHEMA_VERSION: Final = 9
_SCHEMA_V1: Final = 1
_SCHEMA_V2: Final = 2
_SCHEMA_V3: Final = 3
_SCHEMA_V4: Final = 4
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


def _schema_v2_sql() -> str:
    """Return the additive mutation and relationship schema introduced in v2."""
    uuid_assertion = _uuid_check("assertion_id")
    uuid_changeset = _uuid_check("changeset_id")
    uuid_intake = _uuid_check("intake_artifact_id")
    return f"""
CREATE TABLE changesets (
    changeset_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_changeset}),
    command_scope TEXT NOT NULL CHECK (length(command_scope) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    base_revision INTEGER NOT NULL CHECK (typeof(base_revision) = 'integer' AND base_revision >= 0),
    committed_revision INTEGER NOT NULL
        CHECK (typeof(committed_revision) = 'integer' AND committed_revision >= base_revision),
    state_changed INTEGER NOT NULL CHECK (state_changed IN (0, 1)),
    actor TEXT NOT NULL CHECK (length(actor) > 0),
    reason TEXT,
    confirmation_json TEXT,
    reversal_of_changeset_id TEXT REFERENCES changesets(changeset_id),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE (command_scope, idempotency_key),
    CHECK (
        (state_changed = 0 AND committed_revision = base_revision)
        OR (state_changed = 1 AND committed_revision = base_revision + 1)
    ),
    CHECK (reversal_of_changeset_id IS NULL OR reversal_of_changeset_id <> changeset_id)
);

CREATE TABLE changeset_entries (
    changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id),
    entry_index INTEGER NOT NULL CHECK (typeof(entry_index) = 'integer' AND entry_index >= 0),
    entity_kind TEXT NOT NULL CHECK (length(entity_kind) > 0),
    entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
    action TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete', 'assert', 'link')),
    before_json TEXT,
    after_json TEXT,
    PRIMARY KEY (changeset_id, entry_index),
    CHECK (before_json IS NOT NULL OR after_json IS NOT NULL)
);

CREATE TABLE audit_events (
    audit_event_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("audit_event_id")}),
    changeset_id TEXT NOT NULL UNIQUE REFERENCES changesets(changeset_id),
    event_kind TEXT NOT NULL CHECK (length(event_kind) > 0),
    event_json TEXT NOT NULL CHECK (length(event_json) > 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);

CREATE TABLE idempotency_requests (
    command_scope TEXT NOT NULL CHECK (length(command_scope) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    request_digest TEXT NOT NULL CHECK (
        length(request_digest) = 64 AND request_digest NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK (status IN ('pending', 'committed')),
    changeset_id TEXT UNIQUE REFERENCES changesets(changeset_id),
    result_json TEXT,
    base_revision INTEGER,
    committed_revision INTEGER,
    state_changed INTEGER CHECK (state_changed IN (0, 1)),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    PRIMARY KEY (command_scope, idempotency_key),
    CHECK (
        (status = 'pending' AND changeset_id IS NULL AND result_json IS NULL
            AND base_revision IS NULL AND committed_revision IS NULL AND state_changed IS NULL)
        OR
        (status = 'committed' AND changeset_id IS NOT NULL AND result_json IS NOT NULL
            AND base_revision IS NOT NULL AND committed_revision IS NOT NULL
            AND state_changed IS NOT NULL)
    )
);

CREATE TABLE ownership_assertion_sets (
    assertion_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_assertion}),
    account_id TEXT NOT NULL REFERENCES accounts(entity_id),
    effective_from TEXT CHECK (
        effective_from IS NULL
        OR coalesce(strftime('%Y-%m-%d', effective_from) = effective_from, 0)
    ),
    effective_to TEXT CHECK (
        effective_to IS NULL
        OR coalesce(strftime('%Y-%m-%d', effective_to) = effective_to, 0)
    ),
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'partial', 'unknown')),
    unknown_remainder INTEGER NOT NULL CHECK (unknown_remainder IN (0, 1)),
    confirmation_state TEXT NOT NULL
        CHECK (confirmation_state IN ('unconfirmed', 'confirmed', 'rejected')),
    evidence_json TEXT NOT NULL CHECK (length(evidence_json) > 1),
    confirmed_at TEXT,
    supersedes_assertion_id TEXT REFERENCES ownership_assertion_sets(assertion_id),
    created_changeset_id TEXT REFERENCES changesets(changeset_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    CHECK (
        (completeness = 'complete' AND unknown_remainder = 0)
        OR (completeness IN ('partial', 'unknown') AND unknown_remainder = 1)
    ),
    CHECK (
        (confirmation_state = 'confirmed' AND confirmed_at IS NOT NULL)
        OR (confirmation_state <> 'confirmed' AND confirmed_at IS NULL)
    ),
    CHECK (supersedes_assertion_id IS NULL OR supersedes_assertion_id <> assertion_id)
);

CREATE TABLE ownership_assertion_shares (
    assertion_id TEXT NOT NULL REFERENCES ownership_assertion_sets(assertion_id),
    party_id TEXT NOT NULL REFERENCES parties(entity_id),
    share_value_id TEXT NOT NULL UNIQUE REFERENCES rate_values(value_id),
    PRIMARY KEY (assertion_id, party_id)
);

CREATE TABLE entity_relation_assertions (
    assertion_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_assertion}),
    subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    object_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    relation_kind TEXT NOT NULL CHECK (
        relation_kind IN ('includes', 'overlaps', 'excludes', 'unknown')
    ),
    effective_from TEXT CHECK (
        effective_from IS NULL
        OR coalesce(strftime('%Y-%m-%d', effective_from) = effective_from, 0)
    ),
    effective_to TEXT CHECK (
        effective_to IS NULL
        OR coalesce(strftime('%Y-%m-%d', effective_to) = effective_to, 0)
    ),
    confirmation_state TEXT NOT NULL
        CHECK (confirmation_state IN ('unconfirmed', 'confirmed', 'rejected')),
    evidence_json TEXT NOT NULL CHECK (length(evidence_json) > 1),
    confirmed_at TEXT,
    supersedes_assertion_id TEXT REFERENCES entity_relation_assertions(assertion_id),
    created_changeset_id TEXT REFERENCES changesets(changeset_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (subject_entity_id <> object_entity_id),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    CHECK (
        (confirmation_state = 'confirmed' AND confirmed_at IS NOT NULL)
        OR (confirmation_state <> 'confirmed' AND confirmed_at IS NULL)
    ),
    CHECK (supersedes_assertion_id IS NULL OR supersedes_assertion_id <> assertion_id)
);

CREATE TABLE agent_intake_artifacts (
    intake_artifact_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_intake}),
    source_artifact_id TEXT NOT NULL UNIQUE REFERENCES source_artifacts(source_artifact_id),
    media_type TEXT NOT NULL CHECK (length(media_type) > 0),
    evidence_json TEXT NOT NULL CHECK (length(evidence_json) > 1),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0)
);

CREATE TABLE agent_intake_occurrences (
    occurrence_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("occurrence_id")}),
    intake_artifact_id TEXT NOT NULL REFERENCES agent_intake_artifacts(intake_artifact_id),
    channel TEXT NOT NULL CHECK (length(channel) > 0),
    received_at TEXT NOT NULL CHECK (length(received_at) > 0),
    occurrence_json TEXT NOT NULL CHECK (length(occurrence_json) > 1)
);

CREATE TABLE agent_intake_extractions (
    extraction_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("extraction_id")}),
    occurrence_id TEXT NOT NULL REFERENCES agent_intake_occurrences(occurrence_id),
    extractor TEXT NOT NULL CHECK (length(extractor) > 0),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 1),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE (occurrence_id, extractor, payload_digest)
);

CREATE TABLE agent_intake_proposals (
    proposal_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("proposal_id")}),
    extraction_id TEXT NOT NULL REFERENCES agent_intake_extractions(extraction_id),
    policy_version TEXT NOT NULL CHECK (length(policy_version) > 0),
    command_scope TEXT NOT NULL CHECK (length(command_scope) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    expected_generation TEXT NOT NULL CHECK ({_uuid_check("expected_generation")}),
    expected_revision INTEGER NOT NULL
        CHECK (typeof(expected_revision) = 'integer' AND expected_revision >= 0),
    payload_json TEXT NOT NULL CHECK (length(payload_json) > 1),
    payload_digest TEXT NOT NULL CHECK (
        length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    UNIQUE (command_scope, idempotency_key),
    UNIQUE (
        extraction_id, command_scope, policy_version, payload_digest,
        expected_generation, expected_revision
    )
);

CREATE TABLE agent_intake_confirmations (
    confirmation_id TEXT PRIMARY KEY NOT NULL CHECK ({_uuid_check("confirmation_id")}),
    proposal_id TEXT NOT NULL REFERENCES agent_intake_proposals(proposal_id),
    confirmation_state TEXT NOT NULL CHECK (confirmation_state IN ('confirmed', 'rejected')),
    actor TEXT NOT NULL CHECK (length(actor) > 0),
    confirmation_json TEXT NOT NULL CHECK (length(confirmation_json) > 1),
    confirmed_at TEXT NOT NULL CHECK (length(confirmed_at) > 0)
);

CREATE TABLE agent_intake_applications (
    proposal_id TEXT PRIMARY KEY NOT NULL REFERENCES agent_intake_proposals(proposal_id),
    confirmation_id TEXT NOT NULL UNIQUE REFERENCES agent_intake_confirmations(confirmation_id),
    changeset_id TEXT NOT NULL UNIQUE REFERENCES changesets(changeset_id)
        DEFERRABLE INITIALLY DEFERRED,
    applied_at TEXT NOT NULL CHECK (length(applied_at) > 0)
);

CREATE INDEX idx_changesets_revision ON changesets(committed_revision);
CREATE INDEX idx_ownership_account_interval
    ON ownership_assertion_sets(account_id, effective_from, effective_to);
CREATE INDEX idx_relations_subject_object
    ON entity_relation_assertions(subject_entity_id, object_entity_id);
"""


def _schema_v3_sql() -> str:
    """Return the canonical configuration-head schema introduced in v3."""
    return """
CREATE TABLE config_heads (
    config_kind TEXT PRIMARY KEY NOT NULL
        CHECK (config_kind IN ('rules', 'goals', 'assets', 'scenarios', 'schema', 'other')),
    revision_id TEXT NOT NULL UNIQUE REFERENCES config_revisions(entity_id),
    updated_changeset_id TEXT REFERENCES changesets(changeset_id) DEFERRABLE INITIALLY DEFERRED,
    updated_at TEXT NOT NULL CHECK (length(updated_at) > 0)
);
"""


def _schema_v4_sql() -> str:
    """Return the source-evidence link schema introduced in v4."""
    uuid_link = _uuid_check("link_id")
    return f"""
CREATE TABLE transaction_source_links (
    link_id TEXT PRIMARY KEY NOT NULL CHECK ({uuid_link}),
    transaction_id TEXT NOT NULL REFERENCES transactions(entity_id),
    provenance_id TEXT NOT NULL UNIQUE REFERENCES record_provenance(provenance_id),
    observation_id TEXT NOT NULL REFERENCES observations(entity_id),
    link_kind TEXT NOT NULL CHECK (link_kind IN ('origin', 'duplicate_evidence')),
    created_changeset_id TEXT NOT NULL REFERENCES changesets(changeset_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE UNIQUE INDEX uq_transaction_origin_source_link
    ON transaction_source_links(transaction_id)
    WHERE link_kind = 'origin';
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

_V2_IMMUTABLE_TABLES = (
    "changesets",
    "changeset_entries",
    "audit_events",
    "ownership_assertion_sets",
    "ownership_assertion_shares",
    "entity_relation_assertions",
    "agent_intake_artifacts",
    "agent_intake_occurrences",
    "agent_intake_extractions",
    "agent_intake_proposals",
    "agent_intake_confirmations",
    "agent_intake_applications",
)

_V2_REINSERT_EXISTS = {
    "changesets": "changeset_id = NEW.changeset_id OR "
    "(command_scope = NEW.command_scope AND idempotency_key = NEW.idempotency_key)",
    "changeset_entries": "changeset_id = NEW.changeset_id AND entry_index = NEW.entry_index",
    "audit_events": "audit_event_id = NEW.audit_event_id OR changeset_id = NEW.changeset_id",
    "ownership_assertion_sets": "assertion_id = NEW.assertion_id",
    "ownership_assertion_shares": "(assertion_id = NEW.assertion_id AND party_id = NEW.party_id) "
    "OR share_value_id = NEW.share_value_id",
    "entity_relation_assertions": "assertion_id = NEW.assertion_id",
    "agent_intake_artifacts": "intake_artifact_id = NEW.intake_artifact_id "
    "OR source_artifact_id = NEW.source_artifact_id",
    "agent_intake_occurrences": "occurrence_id = NEW.occurrence_id",
    "agent_intake_extractions": "extraction_id = NEW.extraction_id OR "
    "(occurrence_id = NEW.occurrence_id AND extractor = NEW.extractor "
    "AND payload_digest = NEW.payload_digest)",
    "agent_intake_proposals": "proposal_id = NEW.proposal_id OR "
    "(command_scope = NEW.command_scope AND idempotency_key = NEW.idempotency_key) OR "
    "(extraction_id = NEW.extraction_id AND command_scope = NEW.command_scope "
    "AND policy_version = NEW.policy_version AND payload_digest = NEW.payload_digest "
    "AND expected_generation = NEW.expected_generation "
    "AND expected_revision = NEW.expected_revision)",
    "agent_intake_confirmations": "confirmation_id = NEW.confirmation_id",
    "agent_intake_applications": "proposal_id = NEW.proposal_id OR "
    "confirmation_id = NEW.confirmation_id OR changeset_id = NEW.changeset_id",
}


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


def _resolve_schema_version(expected_schema_version: int | None) -> int:
    """Select an implemented exact schema; omission retains the runtime current contract."""
    version = SQLITE_SCHEMA_VERSION if expected_schema_version is None else expected_schema_version
    if type(version) is not int or version not in {4, 5, 6, 7, 8, 9}:
        raise RepositoryVersionError("Unsupported requested SQLite schema version.")
    return version


def _initialize_schema(
    connection: sqlite3.Connection,
    dataset_generation: str,
    *,
    dataset_revision: int = 0,
    schema_version: int,
) -> None:
    """Install the selected schema without following future runtime schema additions."""
    _resolve_schema_version(schema_version)
    steps = {
        4: (_apply_schema_v2, _apply_schema_v3, _apply_schema_v4),
        5: (_apply_schema_v2, _apply_schema_v3, _apply_schema_v4, apply_schema_v5),
        6: (_apply_schema_v2, _apply_schema_v3, _apply_schema_v4, apply_schema_v5, apply_schema_v6),
        7: (
            _apply_schema_v2,
            _apply_schema_v3,
            _apply_schema_v4,
            apply_schema_v5,
            apply_schema_v6,
            apply_schema_v7,
        ),
        8: (
            _apply_schema_v2,
            _apply_schema_v3,
            _apply_schema_v4,
            apply_schema_v5,
            apply_schema_v6,
            apply_schema_v7,
            apply_schema_v8,
        ),
        9: (
            _apply_schema_v2,
            _apply_schema_v3,
            _apply_schema_v4,
            apply_schema_v5,
            apply_schema_v6,
            apply_schema_v7,
            apply_schema_v8,
            apply_schema_v9,
        ),
    }[schema_version]
    _apply_schema_v1(connection, dataset_generation, dataset_revision=dataset_revision)
    for apply_schema in steps:
        apply_schema(connection)


def initialize_repository(paths: GenerationPaths, dataset_generation: str) -> RepositoryInfo:
    """Build the current schema through every migration and publish a new candidate."""
    validate_entity_id(dataset_generation)
    _prepare_generation_layout(paths)
    if paths.database.exists() or paths.database.is_symlink():
        raise RepositoryPathError("Repository database already exists and will not be replaced.")
    staging = paths.root / f".finjuice-sqlite-staging-{uuid.uuid4().hex}"
    connection = _connect_builder(staging)
    try:
        _initialize_schema(connection, dataset_generation, schema_version=SQLITE_SCHEMA_VERSION)
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
    expected_schema_version: int | None = None,
) -> RepositoryInfo:
    """Inspect the latest stable DB/WAL state without SQLite-opening the original files."""
    version = _resolve_schema_version(expected_schema_version)
    with inspection_snapshot(database, scratch_root=scratch_root) as snapshot:
        try:
            connection = _connect_snapshot(snapshot)
            try:
                return _read_info(connection, expected_schema_version=version)
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise RepositoryIntegrityError("Repository snapshot could not be read.") from exc


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
            source_info = _read_upgrade_info(source_connection)
            if source_info.schema_version > SQLITE_SCHEMA_VERSION:
                raise RepositoryVersionError(
                    f"SQLite schema v{source_info.schema_version} is newer than supported "
                    f"v{SQLITE_SCHEMA_VERSION}."
                )
            if source_info.schema_version < _SCHEMA_V1:
                raise RepositoryVersionError(
                    f"SQLite schema v{source_info.schema_version} has no supported upgrade path."
                )
            staging = destination.root / f".finjuice-sqlite-staging-{uuid.uuid4().hex}"
            target_connection = _connect_builder(staging)
            try:
                source_connection.backup(target_connection)
                _normalize_journal_mode(target_connection)
                _upgrade_schema_to_current(target_connection, source_info.schema_version)
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
                _SCHEMA_V1,
                dataset_generation,
                dataset_revision,
            ),
        )
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (?, ?, ?)",
            (
                _SCHEMA_V1,
                "initial_authoritative_storage",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
        connection.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {_SCHEMA_V1}")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _apply_schema_v2(connection: sqlite3.Connection) -> None:
    """Apply the real v1-to-v2 mutation and relationship migration."""
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != _SCHEMA_V1:
        raise RepositoryVersionError("Schema v2 requires a schema v1 repository.")
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n" + _schema_v2_sql() + _immutable_trigger_sql_for_v2()
        )
        applied_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (?, ?, ?)",
            (_SCHEMA_V2, "atomic_mutations_and_relationship_assertions", applied_at),
        )
        connection.execute(
            "UPDATE repository_meta SET schema_version = ? WHERE singleton = 1",
            (_SCHEMA_V2,),
        )
        connection.execute(f"PRAGMA user_version = {_SCHEMA_V2}")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _immutable_trigger_sql_for_v2() -> str:
    """Create immutability guards only for tables introduced by schema v2."""
    statements: list[str] = []
    for table in _V2_IMMUTABLE_TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
            )
        )
        statements.append(
            # Table and predicate text come only from the closed module-level allowlists above.
            f"CREATE TRIGGER {table}_no_reinsert BEFORE INSERT ON {table} "  # nosec B608
            f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {_V2_REINSERT_EXISTS[table]}) "
            "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;"
        )
    statements.extend(
        (
            "CREATE TRIGGER idempotency_requests_guarded_update "
            "BEFORE UPDATE ON idempotency_requests WHEN "
            "OLD.status <> 'pending' OR NEW.status <> 'committed' "
            "OR NEW.command_scope <> OLD.command_scope "
            "OR NEW.idempotency_key <> OLD.idempotency_key "
            "OR NEW.request_digest <> OLD.request_digest "
            "OR NEW.created_at <> OLD.created_at "
            "BEGIN SELECT RAISE(ABORT, 'protected idempotency receipt'); END;",
            "CREATE TRIGGER idempotency_requests_no_delete BEFORE DELETE ON idempotency_requests "
            "BEGIN SELECT RAISE(ABORT, 'protected idempotency receipt'); END;",
            "CREATE TRIGGER idempotency_requests_no_reinsert BEFORE INSERT "
            "ON idempotency_requests WHEN EXISTS (SELECT 1 FROM idempotency_requests "
            "WHERE command_scope = NEW.command_scope AND idempotency_key = NEW.idempotency_key) "
            "BEGIN SELECT RAISE(ABORT, 'protected idempotency receipt'); END;",
        )
    )
    return "\n".join(statements)


def _apply_schema_v3(connection: sqlite3.Connection) -> None:
    """Apply the v2-to-v3 canonical configuration-head migration."""
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != _SCHEMA_V2:
        raise RepositoryVersionError("Schema v3 requires a schema v2 repository.")
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n" + _schema_v3_sql() + _immutable_trigger_sql_for_v3()
        )
        applied_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (?, ?, ?)",
            (_SCHEMA_V3, "canonical_configuration_heads", applied_at),
        )
        connection.execute(
            "UPDATE repository_meta SET schema_version = ? WHERE singleton = 1",
            (_SCHEMA_V3,),
        )
        connection.execute(f"PRAGMA user_version = {_SCHEMA_V3}")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _immutable_trigger_sql_for_v3() -> str:
    """Create protection guards for the configuration heads introduced in v3."""
    return "\n".join(
        (
            "CREATE TRIGGER config_heads_guarded_update BEFORE UPDATE ON config_heads WHEN "
            "NEW.config_kind <> OLD.config_kind OR NEW.revision_id = OLD.revision_id "
            "OR NEW.updated_changeset_id IS NULL "
            "BEGIN SELECT RAISE(ABORT, 'protected config head'); END;",
            "CREATE TRIGGER config_heads_no_delete BEFORE DELETE ON config_heads "
            "BEGIN SELECT RAISE(ABORT, 'protected config head'); END;",
            "CREATE TRIGGER config_heads_no_reinsert BEFORE INSERT ON config_heads "
            "WHEN EXISTS (SELECT 1 FROM config_heads WHERE config_kind = NEW.config_kind) "
            "BEGIN SELECT RAISE(ABORT, 'protected config head'); END;",
        )
    )


def _upgrade_schema_to_current(connection: sqlite3.Connection, source_version: int) -> None:
    """Apply every later supported schema version onto a cloned candidate."""
    if source_version == _SCHEMA_V1:
        _apply_schema_v2(connection)
    if source_version <= _SCHEMA_V2:
        _apply_schema_v3(connection)
    if source_version <= _SCHEMA_V3:
        _apply_schema_v4(connection)
    if source_version <= _SCHEMA_V4:
        apply_schema_v5(connection)
    if source_version <= 5:
        apply_schema_v6(connection)
    if source_version <= 6:
        apply_schema_v7(connection)
    if source_version <= 7:
        apply_schema_v8(connection)
    if source_version <= 8:
        apply_schema_v9(connection)


def _apply_schema_v4(connection: sqlite3.Connection) -> None:
    """Apply the v3-to-v4 source-evidence link migration."""
    if int(connection.execute("PRAGMA user_version").fetchone()[0]) != _SCHEMA_V3:
        raise RepositoryVersionError("Schema v4 requires a schema v3 repository.")
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n" + _schema_v4_sql() + _immutable_trigger_sql_for_v4()
        )
        applied_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connection.execute(
            "INSERT INTO schema_migrations (schema_version, migration_name, applied_at) "
            "VALUES (?, ?, ?)",
            (_SCHEMA_V4, "transaction_source_evidence_links", applied_at),
        )
        connection.execute(
            "UPDATE repository_meta SET schema_version = ? WHERE singleton = 1",
            (_SCHEMA_V4,),
        )
        connection.execute(f"PRAGMA user_version = {_SCHEMA_V4}")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise


def _immutable_trigger_sql_for_v4() -> str:
    """Create append-only guards for source-evidence links introduced in v4."""
    return "\n".join(
        (
            "CREATE TRIGGER transaction_source_links_no_update "
            "BEFORE UPDATE ON transaction_source_links "
            "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
            "CREATE TRIGGER transaction_source_links_no_delete "
            "BEFORE DELETE ON transaction_source_links "
            "BEGIN SELECT RAISE(ABORT, 'immutable preservation row'); END;",
        )
    )


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


def _read_info(
    connection: sqlite3.Connection, *, expected_schema_version: int | None = None
) -> RepositoryInfo:
    expected_version = _resolve_schema_version(expected_schema_version)
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != SQLITE_APPLICATION_ID:
        raise RepositoryVersionError("SQLite file is not a finjuice authoritative repository.")
    if schema_version != expected_version:
        relation = "newer than" if schema_version > expected_version else "unsupported by"
        raise RepositoryVersionError(
            f"SQLite schema v{schema_version} is {relation} this build "
            f"(supported v{expected_version})."
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


def _read_upgrade_info(connection: sqlite3.Connection) -> RepositoryInfo:
    """Read a supported source identity without mutating an older repository."""
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application_id != SQLITE_APPLICATION_ID:
        raise RepositoryVersionError("SQLite file is not a finjuice authoritative repository.")
    if schema_version > SQLITE_SCHEMA_VERSION:
        raise RepositoryVersionError(
            f"SQLite schema v{schema_version} is newer than supported v{SQLITE_SCHEMA_VERSION}."
        )
    if schema_version < _SCHEMA_V1:
        raise RepositoryVersionError(
            f"SQLite schema v{schema_version} is unsupported and has no upgrade path."
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
    revision = int(row[3])
    if revision < 0:
        raise RepositoryIntegrityError("Dataset revision must be non-negative.")
    return RepositoryInfo(application_id, schema_version, str(row[2]), revision)


def _validate_connection(
    connection: sqlite3.Connection,
    *,
    expected_generation: str | None = None,
    object_paths: GenerationPaths | None = None,
    expected_schema_version: int | None = None,
) -> RepositoryInfo:
    info = _read_info(connection, expected_schema_version=expected_schema_version)
    if expected_generation is not None and info.dataset_generation != expected_generation:
        raise RepositoryIntegrityError("Repository generation does not match the builder request.")
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise RepositoryIntegrityError("SQLite integrity_check failed.")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RepositoryIntegrityError("SQLite foreign_key_check failed.")
    _validate_application_invariants(connection, schema_version=info.schema_version)
    if object_paths is not None:
        _validate_source_objects(connection, object_paths)
    return info


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
