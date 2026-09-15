"""Application-invariant helpers for the SQLite schema contract.

Owns entity/exact subtype checks, source-binding and source-link checks,
ownership/relation/intake invariant validation, and referenced object
verification. Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.schema`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from fractions import Fraction
from typing import Final

from finjuice.pipeline.storage.sqlite.errors import (
    ObjectStoreError,
    RepositoryIntegrityError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.schema_v5 import validate_v5_invariants
from finjuice.pipeline.storage.sqlite.schema_v6 import validate_v6_invariants
from finjuice.pipeline.storage.sqlite.schema_v7 import validate_v7_invariants
from finjuice.pipeline.storage.sqlite.schema_v8 import validate_v8_invariants
from finjuice.pipeline.storage.sqlite.schema_v9 import validate_v9_invariants

_OWNERSHIP_SHARE_UNIT: Final = "ownership_share.v1"
_SCHEMA_V4: Final = 4

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
        "SELECT link_id, observation_id, provenance_id FROM transaction_source_links UNION ALL "
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

_SOURCE_LINK_CHECKS: Final = (
    (
        "SELECT link.link_id FROM transaction_source_links AS link "
        "JOIN record_provenance AS provenance ON provenance.provenance_id = link.provenance_id "
        "JOIN observations AS observation ON observation.entity_id = link.observation_id "
        "WHERE provenance.source_occurrence_id <> observation.source_occurrence_id",
        "A source link joins evidence from different source occurrences.",
    ),
    (
        "SELECT link.link_id FROM transaction_source_links AS link "
        "JOIN transactions AS txn ON txn.entity_id = link.transaction_id "
        "WHERE link.link_kind = 'origin' "
        "AND (link.provenance_id <> txn.provenance_id "
        "OR link.observation_id <> txn.observation_id)",
        "An origin source link does not match the transaction's preserved origin.",
    ),
    (
        "SELECT link.link_id FROM transaction_source_links AS link "
        "JOIN transactions AS txn ON txn.entity_id = link.transaction_id "
        "WHERE link.link_kind = 'duplicate_evidence' "
        "AND link.provenance_id = txn.provenance_id",
        "Duplicate evidence must not reuse the transaction origin provenance.",
    ),
    (
        "SELECT transaction_id FROM transaction_source_links "
        "WHERE link_kind = 'origin' GROUP BY transaction_id HAVING COUNT(*) > 1",
        "A transaction has more than one origin source link.",
    ),
    (
        "SELECT link.link_id FROM transaction_source_links AS link "
        "JOIN transactions AS txn ON txn.provenance_id = link.provenance_id "
        "WHERE txn.entity_id <> link.transaction_id",
        "A source link reassigns another transaction's origin provenance.",
    ),
)


def _validate_application_invariants(
    connection: sqlite3.Connection, *, schema_version: int
) -> None:
    from finjuice.pipeline.storage.sqlite.schema import _resolve_schema_version

    _resolve_schema_version(schema_version)
    _validate_v4_application_invariants(connection)
    if schema_version >= 5:
        validate_v5_invariants(connection)
    if schema_version >= 6:
        validate_v6_invariants(connection)
    if schema_version >= 7:
        validate_v7_invariants(connection)
    if schema_version >= 8:
        validate_v8_invariants(connection)
    if schema_version >= 9:
        validate_v9_invariants(connection)


def _validate_v4_application_invariants(connection: sqlite3.Connection) -> None:
    """Validate the complete v4 contract, independent of later schema additions."""
    for query in _ENTITY_SUBTYPE_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError("An entity is missing its matching typed row.")
    for query in _EXACT_SUBTYPE_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError("An exact value is missing its matching subtype row.")
    _validate_schema_migration_ledger(connection)
    _validate_source_bindings(connection)
    _validate_v2_invariants(connection)
    _validate_v3_invariants(connection)
    _validate_v4_invariants(connection)
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


def _validate_v2_invariants(connection: sqlite3.Connection) -> None:
    """Validate cross-row invariants introduced by the mutation schema."""
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if schema_version < 2:
        return
    pending = connection.execute(
        "SELECT 1 FROM idempotency_requests WHERE status <> 'committed' LIMIT 1"
    ).fetchone()
    if pending is not None:
        raise RepositoryIntegrityError("A published repository contains a pending request.")
    receipt_mismatch = connection.execute(
        "SELECT 1 FROM idempotency_requests AS request "
        "JOIN changesets AS changeset ON changeset.changeset_id = request.changeset_id "
        "WHERE request.command_scope <> changeset.command_scope "
        "OR request.idempotency_key <> changeset.idempotency_key "
        "OR request.base_revision <> changeset.base_revision "
        "OR request.committed_revision <> changeset.committed_revision "
        "OR request.state_changed <> changeset.state_changed LIMIT 1"
    ).fetchone()
    if receipt_mismatch is not None:
        raise RepositoryIntegrityError("An idempotency receipt disagrees with its changeset.")
    _validate_receipt_envelopes(connection)
    _validate_ownership_assertions(connection)
    _validate_relation_assertions(connection)
    _validate_intake_applications(connection)


def _validate_v3_invariants(connection: sqlite3.Connection) -> None:
    """Validate cross-row invariants introduced by canonical configuration heads."""
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if schema_version < 3:
        return
    head_mismatch = connection.execute(
        "SELECT 1 FROM config_heads AS head "
        "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
        "WHERE head.config_kind <> revision.config_kind LIMIT 1"
    ).fetchone()
    if head_mismatch is not None:
        raise RepositoryIntegrityError("A config head references another configuration kind.")


def _validate_v4_invariants(connection: sqlite3.Connection) -> None:
    """Validate source-evidence link bindings introduced in schema v4."""
    schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if schema_version < _SCHEMA_V4:
        return
    for query, message in _SOURCE_LINK_CHECKS:
        if connection.execute(query).fetchone() is not None:
            raise RepositoryIntegrityError(message)


def _validate_ownership_assertions(connection: sqlite3.Connection) -> None:
    totals, metadata = _collect_ownership_state(connection)
    for assertion_id, (account_id, completeness, confirmation, supersedes) in metadata.items():
        if confirmation == "confirmed" and completeness == "complete" and totals[assertion_id] != 1:
            raise RepositoryIntegrityError("Complete confirmed ownership shares must total one.")
        if supersedes is not None:
            previous = metadata.get(supersedes)
            if previous is None or previous[0] != account_id:
                raise RepositoryIntegrityError(
                    "An ownership correction must supersede an assertion for the same account."
                )
    _validate_active_ownership_overlap(connection)


def _collect_ownership_state(
    connection: sqlite3.Connection,
) -> tuple[dict[str, Fraction], dict[str, tuple[str, str, str, str | None]]]:
    rows = connection.execute(
        "SELECT assertion.assertion_id, assertion.account_id, assertion.completeness, "
        "assertion.confirmation_state, assertion.supersedes_assertion_id, "
        "share.share_value_id, value.coefficient, value.scale, rate.unit, "
        "assertion.effective_from, assertion.effective_to "
        "FROM ownership_assertion_sets AS assertion "
        "LEFT JOIN ownership_assertion_shares AS share "
        "ON share.assertion_id = assertion.assertion_id "
        "LEFT JOIN exact_values AS value ON value.value_id = share.share_value_id "
        "LEFT JOIN rate_values AS rate ON rate.value_id = share.share_value_id "
        "ORDER BY assertion.assertion_id, share.party_id"
    ).fetchall()
    totals: dict[str, Fraction] = {}
    metadata: dict[str, tuple[str, str, str, str | None]] = {}
    for (
        assertion_id,
        account_id,
        completeness,
        confirmation_state,
        supersedes,
        share_value_id,
        coefficient,
        scale,
        unit,
        effective_from,
        effective_to,
    ) in rows:
        key = str(assertion_id)
        metadata[key] = (
            str(account_id),
            str(completeness),
            str(confirmation_state),
            None if supersedes is None else str(supersedes),
        )
        totals.setdefault(key, Fraction(0))
        _validate_effective_interval(effective_from, effective_to)
        if share_value_id is not None and unit != _OWNERSHIP_SHARE_UNIT:
            raise RepositoryIntegrityError(
                "An ownership share must use the ownership_share.v1 semantic unit."
            )
        if coefficient is not None:
            share = Fraction(int(str(coefficient)), 10 ** int(scale))
            if share <= 0 or share > 1:
                raise RepositoryIntegrityError("An ownership share is outside (0, 1].")
            totals[key] += share
        if confirmation_state == "confirmed" and totals[key] > 1:
            raise RepositoryIntegrityError("Confirmed ownership shares exceed one.")
    return totals, metadata


def _validate_active_ownership_overlap(connection: sqlite3.Connection) -> None:
    overlap = connection.execute(
        "SELECT 1 FROM ownership_assertion_sets AS left_set "
        "JOIN ownership_assertion_sets AS right_set "
        "ON left_set.account_id = right_set.account_id "
        "AND left_set.assertion_id < right_set.assertion_id "
        "WHERE left_set.confirmation_state = 'confirmed' "
        "AND right_set.confirmation_state = 'confirmed' "
        "AND NOT EXISTS (SELECT 1 FROM ownership_assertion_sets AS successor "
        "  WHERE successor.supersedes_assertion_id = left_set.assertion_id "
        "  AND successor.confirmation_state = 'confirmed') "
        "AND NOT EXISTS (SELECT 1 FROM ownership_assertion_sets AS successor "
        "  WHERE successor.supersedes_assertion_id = right_set.assertion_id "
        "  AND successor.confirmation_state = 'confirmed') "
        "AND coalesce(left_set.effective_to, '9999-12-31T23:59:59Z') "
        ">= coalesce(right_set.effective_from, '') "
        "AND coalesce(right_set.effective_to, '9999-12-31T23:59:59Z') "
        ">= coalesce(left_set.effective_from, '') LIMIT 1"
    ).fetchone()
    if overlap is not None:
        raise RepositoryIntegrityError("Active confirmed ownership assertions overlap.")


def _validate_receipt_envelopes(connection: sqlite3.Connection) -> None:
    from finjuice.pipeline.storage.sqlite.intake_lineage import validated_lineage

    validated_lineage(connection)
    for (result_json,) in connection.execute(
        "SELECT result_json FROM idempotency_requests WHERE status = 'committed'"
    ).fetchall():
        try:
            parsed = json.loads(str(result_json), parse_constant=_reject_json_constant)
            canonical = json.dumps(
                parsed,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError("A stored mutation receipt is invalid JSON.") from exc
        if (
            canonical != result_json
            or not isinstance(parsed, dict)
            or set(parsed)
            != {
                "result",
                "retained_artifacts",
            }
        ):
            raise RepositoryIntegrityError("A stored mutation receipt is not canonical.")
        if not isinstance(parsed["result"], dict) or not isinstance(
            parsed["retained_artifacts"], list
        ):
            raise RepositoryIntegrityError("A stored mutation receipt has an invalid envelope.")
        if any(not isinstance(item, str) or not item for item in parsed["retained_artifacts"]):
            raise RepositoryIntegrityError("A stored mutation receipt has an invalid artifact ID.")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


def _validate_intake_applications(connection: sqlite3.Connection) -> None:
    invalid = connection.execute(
        "SELECT 1 FROM agent_intake_applications AS application "
        "JOIN agent_intake_confirmations AS confirmation "
        "ON confirmation.confirmation_id = application.confirmation_id "
        "JOIN agent_intake_proposals AS proposal ON proposal.proposal_id = application.proposal_id "
        "JOIN changesets AS changeset ON changeset.changeset_id = application.changeset_id "
        "WHERE confirmation.proposal_id <> application.proposal_id "
        "OR confirmation.confirmation_state <> 'confirmed' "
        "OR proposal.command_scope <> changeset.command_scope "
        "OR proposal.idempotency_key <> changeset.idempotency_key "
        "OR proposal.payload_digest <> changeset.payload_digest "
        "OR proposal.expected_generation <> "
        "(SELECT dataset_generation FROM repository_meta WHERE singleton = 1) "
        "OR proposal.expected_revision <> changeset.base_revision LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise RepositoryIntegrityError("An intake application lacks a matching confirmed request.")
    digest_rows = connection.execute(
        "SELECT payload_json, payload_digest FROM agent_intake_extractions "
        "UNION ALL SELECT payload_json, payload_digest FROM agent_intake_proposals"
    ).fetchall()
    for payload_json, payload_digest in digest_rows:
        try:
            parsed = json.loads(str(payload_json))
            canonical = json.dumps(
                parsed,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError("An intake payload is not canonical JSON.") from exc
        if canonical != payload_json:
            raise RepositoryIntegrityError("An intake payload is not canonical JSON.")
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != payload_digest:
            raise RepositoryIntegrityError("An intake payload digest is invalid.")


def _validate_relation_assertions(connection: sqlite3.Connection) -> None:
    """Require coherent active assertions and pair-preserving corrections."""
    for effective_from, effective_to in connection.execute(
        "SELECT effective_from, effective_to FROM entity_relation_assertions"
    ).fetchall():
        _validate_effective_interval(effective_from, effective_to)
    invalid = connection.execute(
        "SELECT 1 FROM entity_relation_assertions AS correction "
        "LEFT JOIN entity_relation_assertions AS original "
        "ON original.assertion_id = correction.supersedes_assertion_id "
        "WHERE correction.supersedes_assertion_id IS NOT NULL "
        "AND (original.assertion_id IS NULL "
        "OR original.subject_entity_id <> correction.subject_entity_id "
        "OR original.object_entity_id <> correction.object_entity_id) LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise RepositoryIntegrityError(
            "A relation correction must supersede the same ordered entity pair."
        )
    contradiction = connection.execute(
        "SELECT 1 FROM entity_relation_assertions AS left_assertion "
        "JOIN entity_relation_assertions AS right_assertion "
        "ON left_assertion.subject_entity_id = right_assertion.subject_entity_id "
        "AND left_assertion.object_entity_id = right_assertion.object_entity_id "
        "AND left_assertion.assertion_id < right_assertion.assertion_id "
        "WHERE left_assertion.confirmation_state = 'confirmed' "
        "AND right_assertion.confirmation_state = 'confirmed' "
        "AND ((left_assertion.relation_kind = 'excludes' "
        "AND right_assertion.relation_kind IN ('includes', 'overlaps')) "
        "OR (right_assertion.relation_kind = 'excludes' "
        "AND left_assertion.relation_kind IN ('includes', 'overlaps'))) "
        "AND NOT EXISTS (SELECT 1 FROM entity_relation_assertions AS successor "
        "  WHERE successor.supersedes_assertion_id = left_assertion.assertion_id "
        "  AND successor.confirmation_state = 'confirmed') "
        "AND NOT EXISTS (SELECT 1 FROM entity_relation_assertions AS successor "
        "  WHERE successor.supersedes_assertion_id = right_assertion.assertion_id "
        "  AND successor.confirmation_state = 'confirmed') "
        "AND coalesce(left_assertion.effective_to, '9999-12-31') "
        ">= coalesce(right_assertion.effective_from, '0001-01-01') "
        "AND coalesce(right_assertion.effective_to, '9999-12-31') "
        ">= coalesce(left_assertion.effective_from, '0001-01-01') LIMIT 1"
    ).fetchone()
    if contradiction is not None:
        raise RepositoryIntegrityError("Active confirmed relation assertions contradict.")


def _validate_effective_interval(effective_from: object, effective_to: object) -> None:
    start = None if effective_from is None else str(effective_from)
    end = None if effective_to is None else str(effective_to)
    if not _is_canonical_calendar_date(start) or not _is_canonical_calendar_date(end):
        raise RepositoryIntegrityError("Effective bounds must be canonical calendar dates.")
    if start is not None and end is not None and end < start:
        raise RepositoryIntegrityError("Effective date range is reversed.")


def _is_canonical_calendar_date(value: str | None) -> bool:
    if value is None:
        return True
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


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
