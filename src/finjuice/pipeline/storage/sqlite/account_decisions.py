"""Read-only binding impact and explicit exact ownership decisions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from finjuice.pipeline.storage.sqlite.account_bindings import (
    _NAMESPACE,
    ASSET_ACCOUNT_NAMESPACE,
    TRANSACTION_ACCOUNT_NAMESPACE,
    AccountBindingConfirmation,
    resolve_account_binding,
)
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id


@dataclass(frozen=True)
class OwnershipShareDecision:
    party_id: str
    coefficient: str
    scale: int

    def exact_value(self) -> ExactValue:
        """Interpret explicitly supplied coefficient/scale without rounding."""
        return ExactValue(
            coefficient=self.coefficient,
            scale=self.scale,
            lexical=None,
            value_kind="rate",
            origin_kind="calculated",
            unit="ownership_share.v1",
        )


@dataclass(frozen=True)
class OwnershipDecision:
    account_id: str
    completeness: Literal["complete", "partial", "unknown"]
    shares: tuple[OwnershipShareDecision, ...]
    evidence: Mapping[str, Any]
    effective_from: str | None = None
    effective_to: str | None = None
    supersedes_assertion_id: str | None = None


def validate_ownership_decision(connection: sqlite3.Connection, command: OwnershipDecision) -> None:
    """Check explicit evidence and current correction head before existing canonical validation."""
    validate_entity_id(command.account_id)
    if command.completeness not in {"complete", "partial", "unknown"}:
        raise MutationValidationError("Ownership completeness is unsupported.")
    if not isinstance(command.evidence, Mapping) or not command.evidence:
        raise MutationValidationError("Ownership confirmation requires explicit evidence.")
    previous = command.supersedes_assertion_id
    if previous is not None:
        validate_entity_id(previous)
        row = connection.execute(
            "SELECT account_id FROM ownership_assertion_sets WHERE assertion_id = ?", (previous,)
        ).fetchone()
        if row is None or row[0] != command.account_id:
            raise MutationValidationError("Correction must retain the original account.")
        if connection.execute(
            "SELECT 1 FROM ownership_assertion_sets WHERE supersedes_assertion_id = ? "
            "AND confirmation_state = 'confirmed'",
            (previous,),
        ).fetchone():
            raise MutationConflictError("Ownership assertion has already been corrected.")


def binding_impact(
    connection: sqlite3.Connection, command: AccountBindingConfirmation
) -> dict[str, Any]:
    """Describe current materialized scope and the next-import decision without rewriting rows."""
    validate_entity_id(command.account_id)
    if (
        not isinstance(command.source_namespace, str)
        or not _NAMESPACE.fullmatch(command.source_namespace)
        or not isinstance(command.external_key, str)
        or not command.external_key.strip()
        or len(command.external_key) > 512
        or not isinstance(command.evidence, Mapping)
        or not command.evidence
    ):
        raise MutationValidationError("Account binding requires an exact source key and evidence.")
    if not connection.execute(
        "SELECT 1 FROM accounts WHERE entity_id = ?", (command.account_id,)
    ).fetchone():
        raise MutationValidationError("Account binding target does not exist.")
    before = resolve_account_binding(connection, command.source_namespace, command.external_key)
    previous = command.supersedes_binding_id
    if previous is not None and previous not in before.binding_ids:
        raise MutationConflictError(
            "Correction must name a current binding for this exact source key."
        )
    targets = {
        row[0]
        for row in connection.execute(
            "SELECT b.account_id FROM account_source_bindings b WHERE b.source_namespace = ? "
            "AND b.external_key = ? AND b.binding_id <> coalesce(?, '') AND NOT EXISTS "
            "(SELECT 1 FROM account_source_bindings n "
            "WHERE n.supersedes_binding_id = b.binding_id)",
            (command.source_namespace, command.external_key, previous),
        )
    } | {command.account_id}
    supported = command.source_namespace in {TRANSACTION_ACCOUNT_NAMESPACE, ASSET_ACCOUNT_NAMESPACE}
    scope = (
        _transaction_scope(connection, command.external_key)
        if command.source_namespace == TRANSACTION_ACCOUNT_NAMESPACE
        else _asset_scope(connection, command.external_key)
        if command.source_namespace == ASSET_ACCOUNT_NAMESPACE
        else []
    )
    return {
        "source_namespace": command.source_namespace,
        "external_key": command.external_key,
        "before": before.to_dict(),
        "after": {
            "status": "confirmed" if len(targets) == 1 else "ambiguous",
            "account_id": next(iter(targets)) if len(targets) == 1 else None,
            "target_account_ids": sorted(targets),
        },
        "requested_account_id": command.account_id,
        "supersedes_binding_id": previous,
        "importer_supported": supported,
        "observed_scope": scope,
        "scope_basis": "materialized_transactions_with_source_links"
        if command.source_namespace == TRANSACTION_ACCOUNT_NAMESPACE
        else "asset_source_payloads"
        if command.source_namespace == ASSET_ACCOUNT_NAMESPACE
        else "unsupported_namespace",
        "scope_limit": (
            "Only stored exact-key evidence is listed; "
            "unmatched quarantined transaction cells are not inferred."
        ),
        "historical_rows_rewritten": 0,
        "applies_to": "new_exact_import_only" if supported else "no_current_importer",
        "existing_import_replay": "preserves_original_receipt_and_account",
    }


def _transaction_scope(connection: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT t.entity_id, t.account_id, coalesce(l.observation_id, t.observation_id), "
        "coalesce(l.provenance_id, t.provenance_id), p.source_occurrence_id, l.link_kind "
        "FROM transactions t LEFT JOIN transaction_source_links l "
        "ON l.transaction_id = t.entity_id "
        "JOIN record_provenance p ON p.provenance_id = coalesce(l.provenance_id,t.provenance_id) "
        "WHERE t.account_text = ? ORDER BY t.entity_id, p.provenance_id",
        (key,),
    )
    names = (
        "transaction_id",
        "account_id",
        "observation_id",
        "provenance_id",
        "source_occurrence_id",
        "link_kind",
    )
    return [dict(zip(names, row, strict=True)) for row in rows]


def _asset_scope(connection: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT l.payload_json, p.provenance_id, p.source_occurrence_id, a.entity_id, "
        "a.account_id, a.observation_id, a.snapshot_date FROM legacy_payloads l "
        "JOIN record_provenance p ON p.provenance_id = l.provenance_id "
        "LEFT JOIN asset_snapshots a ON a.provenance_id = p.provenance_id ORDER BY p.provenance_id"
    )
    names = (
        "provenance_id",
        "source_occurrence_id",
        "asset_snapshot_id",
        "account_id",
        "observation_id",
        "snapshot_date",
    )
    result = []
    for payload, *values in rows:
        parsed = json.loads(payload)
        if (
            isinstance(parsed, dict)
            and parsed.get("family") == "asset"
            and parsed.get("source_account_id") == key
        ):
            result.append(
                {**dict(zip(names, values, strict=True)), "import_action": parsed.get("action")}
            )
    return result
