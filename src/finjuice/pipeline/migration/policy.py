"""Explicit adapter policy for replaying old and new immutable plans."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.migration.common import MigrationError

LEGACY_POLICY = "legacy_preservation.v1"
CONFIG_HEAD_POLICY = "legacy_preservation.config_heads.v2"
MANUAL_STATE_POLICY = "legacy_preservation.manual_state.v3"


def migration_policy(plan: dict[str, Any]) -> str:
    """Resolve legacy absence without accepting unknown adapter semantics."""
    policy = plan.get("migration_policy", LEGACY_POLICY)
    if not isinstance(policy, str) or policy not in (
        LEGACY_POLICY,
        CONFIG_HEAD_POLICY,
        MANUAL_STATE_POLICY,
    ):
        raise MigrationError("Unsupported migration adapter policy.")
    return policy
