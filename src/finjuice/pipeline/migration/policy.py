"""Explicit adapter policy for replaying old and new immutable plans."""

from __future__ import annotations

from typing import Any, cast

from finjuice.pipeline.migration.common import MigrationError

LEGACY_POLICY = "legacy_preservation.v1"
CONFIG_HEAD_POLICY = "legacy_preservation.config_heads.v2"
MANUAL_STATE_POLICY = "legacy_preservation.manual_state.v3"


_POLICY_SCHEMA_VERSIONS = {
    LEGACY_POLICY: 4,
    CONFIG_HEAD_POLICY: 4,
    MANUAL_STATE_POLICY: 4,
}


def migration_schema_version(policy: str) -> int:
    """Pin immutable adapter policies to their original repository schema."""
    if not isinstance(policy, str) or policy not in _POLICY_SCHEMA_VERSIONS:
        raise MigrationError("Unsupported migration adapter policy.")
    return _POLICY_SCHEMA_VERSIONS[policy]


def migration_policy(plan: dict[str, Any]) -> str:
    """Resolve legacy absence without accepting unknown adapter semantics."""
    policy = plan.get("migration_policy", LEGACY_POLICY)
    migration_schema_version(policy)
    return cast(str, policy)
