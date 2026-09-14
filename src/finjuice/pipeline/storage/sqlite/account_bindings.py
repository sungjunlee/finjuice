"""Explicit runtime source identity decisions and exact-key account resolution."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import new_entity_id, validate_entity_id

TRANSACTION_ACCOUNT_NAMESPACE = "banksalad.transactions.account_text.v1"
ASSET_ACCOUNT_NAMESPACE = "banksalad.assets.account_id.v1"
_NAMESPACE = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True)
class AccountBindingConfirmation:
    """An operator's exact source key, stable target and explicit supporting evidence."""

    source_namespace: str
    external_key: str
    account_id: str
    evidence: Mapping[str, Any]
    supersedes_binding_id: str | None = None


@dataclass(frozen=True)
class AccountBindingResolution:
    """A single current target or an explicitly unresolved set of binding heads."""

    status: Literal["confirmed", "unbound", "ambiguous"]
    account_id: str | None
    binding_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_account_binding(
    connection: sqlite3.Connection, namespace: str, external_key: str
) -> AccountBindingResolution:
    """Resolve only explicitly confirmed exact keys, never normalized display names."""
    rows = connection.execute(
        "SELECT b.binding_id, b.account_id FROM account_source_bindings b "
        "WHERE b.source_namespace = ? AND b.external_key = ? AND NOT EXISTS "
        "(SELECT 1 FROM account_source_bindings newer "
        "WHERE newer.supersedes_binding_id = b.binding_id) "
        "ORDER BY b.binding_id",
        (namespace, external_key),
    ).fetchall()
    targets = {row[1] for row in rows}
    status: Literal["confirmed", "unbound", "ambiguous"] = (
        "unbound" if not targets else "confirmed" if len(targets) == 1 else "ambiguous"
    )
    return AccountBindingResolution(
        status, next(iter(targets)) if len(targets) == 1 else None, tuple(row[0] for row in rows)
    )


def insert_account_binding(
    connection: sqlite3.Connection, command: AccountBindingConfirmation, changeset_id: str
) -> dict[str, Any]:
    """Insert an immutable confirmation/correction inside the caller's mutation transaction."""
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
    if (
        connection.execute(
            "SELECT 1 FROM accounts WHERE entity_id = ?", (command.account_id,)
        ).fetchone()
        is None
    ):
        raise MutationValidationError("Account binding target does not exist.")
    previous = command.supersedes_binding_id
    if previous is not None:
        validate_entity_id(previous)
        row = connection.execute(
            "SELECT source_namespace, external_key FROM account_source_bindings "
            "WHERE binding_id = ?",
            (previous,),
        ).fetchone()
        if row is None or tuple(row) != (command.source_namespace, command.external_key):
            raise MutationValidationError("Correction must retain the original source key.")
        if connection.execute(
            "SELECT 1 FROM account_source_bindings WHERE supersedes_binding_id = ?", (previous,)
        ).fetchone():
            raise MutationConflictError("Account binding has already been corrected.")
    identifier = new_entity_id()
    evidence = json.dumps(
        dict(command.evidence), sort_keys=True, ensure_ascii=False, allow_nan=False
    )
    connection.execute(
        "INSERT INTO account_source_bindings "
        "(binding_id, source_namespace, external_key, account_id, evidence_json, "
        "supersedes_binding_id, created_changeset_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            command.source_namespace,
            command.external_key,
            command.account_id,
            evidence,
            previous,
            changeset_id,
        ),
    )
    return {"binding_id": identifier, **asdict(command)}


def account_binding_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return source candidates and all assertion history from one pinned SQLite view."""
    cursor = connection.execute("SELECT * FROM account_source_bindings ORDER BY binding_id")
    names = [item[0] for item in cursor.description]
    bindings = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    cursor = connection.execute(
        "SELECT entity_id, account_kind, display_name, ownership_state "
        "FROM accounts ORDER BY entity_id"
    )
    accounts = [
        dict(
            zip(("account_id", "account_kind", "display_name", "ownership_state"), row, strict=True)
        )
        for row in cursor.fetchall()
    ]
    candidates: set[tuple[str, str]] = {
        (TRANSACTION_ACCOUNT_NAMESPACE, row[0])
        for row in connection.execute(
            "SELECT DISTINCT account_text FROM transactions WHERE account_text <> ''"
        )
    }
    for (payload,) in connection.execute("SELECT payload_json FROM legacy_payloads"):
        row = json.loads(payload)
        if (
            isinstance(row, dict)
            and row.get("family") == "asset"
            and isinstance(row.get("source_account_id"), str)
        ):
            candidates.add((ASSET_ACCOUNT_NAMESPACE, row["source_account_id"]))
    candidates.update((row["source_namespace"], row["external_key"]) for row in bindings)
    return {
        "accounts": accounts,
        "bindings": bindings,
        "candidates": [
            {
                "source_namespace": namespace,
                "external_key": key,
                **resolve_account_binding(connection, namespace, key).to_dict(),
            }
            for namespace, key in sorted(candidates)
        ],
    }
