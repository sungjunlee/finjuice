"""Authoritative table-surface SQL for repository snapshot reads.

Owns the versioned ``SELECT *`` registry used by :class:`RepositoryReader`.
Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.repository`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from finjuice.pipeline.storage.sqlite.schema import _resolve_schema_version
from finjuice.pipeline.storage.sqlite.schema_v5 import LEGACY_OVERVIEW_TABLES

_READ_TABLE_SQL_V4: Final = {
    "repository_meta": "SELECT * FROM repository_meta",
    "schema_migrations": "SELECT * FROM schema_migrations",
    "entities": "SELECT * FROM entities",
    "migration_identities": "SELECT * FROM migration_identities",
    "source_artifacts": "SELECT * FROM source_artifacts",
    "source_occurrences": "SELECT * FROM source_occurrences",
    "record_provenance": "SELECT * FROM record_provenance",
    "exact_values": "SELECT * FROM exact_values",
    "money_values": "SELECT * FROM money_values",
    "quantity_values": "SELECT * FROM quantity_values",
    "rate_values": "SELECT * FROM rate_values",
    "number_values": "SELECT * FROM number_values",
    "parties": "SELECT * FROM parties",
    "accounts": "SELECT * FROM accounts",
    "resources": "SELECT * FROM resources",
    "observations": "SELECT * FROM observations",
    "config_revisions": "SELECT * FROM config_revisions",
    "config_heads": "SELECT * FROM config_heads",
    "legacy_payloads": "SELECT * FROM legacy_payloads",
    "preservation_issues": "SELECT * FROM preservation_issues",
    "migration_dispositions": "SELECT * FROM migration_dispositions",
    "legacy_identifiers": "SELECT * FROM legacy_identifiers",
    "legacy_identifier_supersessions": "SELECT * FROM legacy_identifier_supersessions",
    "transactions": "SELECT * FROM transactions",
    "transaction_source_links": "SELECT * FROM transaction_source_links",
    "overview_facts": "SELECT * FROM overview_facts",
    "overview_balances": "SELECT * FROM overview_balances",
    "overview_cashflows": "SELECT * FROM overview_cashflows",
    "overview_insurance": "SELECT * FROM overview_insurance",
    "overview_investments": "SELECT * FROM overview_investments",
    "overview_loans": "SELECT * FROM overview_loans",
    "asset_snapshots": "SELECT * FROM asset_snapshots",
    "changesets": "SELECT * FROM changesets",
    "changeset_entries": "SELECT * FROM changeset_entries",
    "audit_events": "SELECT * FROM audit_events",
    "idempotency_requests": "SELECT * FROM idempotency_requests",
    "ownership_assertion_sets": "SELECT * FROM ownership_assertion_sets",
    "ownership_assertion_shares": "SELECT * FROM ownership_assertion_shares",
    "entity_relation_assertions": "SELECT * FROM entity_relation_assertions",
    "agent_intake_artifacts": "SELECT * FROM agent_intake_artifacts",
    "agent_intake_occurrences": "SELECT * FROM agent_intake_occurrences",
    "agent_intake_extractions": "SELECT * FROM agent_intake_extractions",
    "agent_intake_proposals": "SELECT * FROM agent_intake_proposals",
    "agent_intake_confirmations": "SELECT * FROM agent_intake_confirmations",
    "agent_intake_applications": "SELECT * FROM agent_intake_applications",
}


_READ_TABLE_SQL_V5: Final = {
    **_READ_TABLE_SQL_V4,
    **{table: f"SELECT * FROM {table}" for table in LEGACY_OVERVIEW_TABLES},
}


def _read_table_sql(schema_version: int) -> Mapping[str, str]:
    """Return exactly the authoritative table surface of the selected schema."""
    _resolve_schema_version(schema_version)
    if schema_version == 9:
        from finjuice.pipeline.storage.sqlite.schema_v9 import TABLE_KEYS as V9_TABLE_KEYS

        return {
            **_read_table_sql(8),
            **{table: f"SELECT * FROM {table}" for table in V9_TABLE_KEYS},
        }
    if schema_version == 8:
        from finjuice.pipeline.storage.sqlite.schema_v8 import TABLE_KEYS

        return {**_read_table_sql(7), **{table: f"SELECT * FROM {table}" for table in TABLE_KEYS}}
    return {
        4: _READ_TABLE_SQL_V4,
        5: _READ_TABLE_SQL_V5,
        6: {
            **_READ_TABLE_SQL_V5,
            "account_source_bindings": "SELECT * FROM account_source_bindings",
        },
        7: {
            **_READ_TABLE_SQL_V5,
            "account_source_bindings": "SELECT * FROM account_source_bindings",
            "asset_meaning_assertions": "SELECT * FROM asset_meaning_assertions",
        },
    }[schema_version]
