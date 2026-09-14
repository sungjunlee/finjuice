"""Exact, effective-dated ownership evidence without inferred account owners."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import date
from typing import Any, Literal, TypedDict

from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.schema import (
    _reject_json_constant,
    _validate_ownership_assertions,
)


class ShareAmount(TypedDict):
    coefficient: str
    scale: int


class OwnershipShare(TypedDict):
    party_id: str
    share_value_id: str
    share: ShareAmount


class OwnershipAssertion(TypedDict):
    assertion_id: str
    evidence: dict[str, Any]
    confirmation_state: Literal["confirmed", "unconfirmed", "rejected"]
    completeness: Literal["complete", "partial", "unknown"]
    effective_from: str | None
    effective_to: str | None
    supersedes_assertion_id: str | None
    superseded_by: list[str]
    unknown_remainder: bool
    shares: list[OwnershipShare]
    total: ShareAmount
    remainder: ShareAmount | None


class OwnershipProjection(TypedDict):
    account_id: str
    as_of: str
    status: Literal["confirmed", "unconfirmed", "unknown"]
    assertion_id: str | None
    completeness: Literal["complete", "partial", "unknown"]
    unknown_remainder: bool
    shares: list[OwnershipShare]
    remainder: ShareAmount
    assertions: list[OwnershipAssertion]


def _shares(connection: sqlite3.Connection, assertion_id: str) -> list[OwnershipShare]:
    rows = connection.execute(
        "SELECT share.party_id, share.share_value_id, value.coefficient, value.scale "
        "FROM ownership_assertion_shares AS share "
        "JOIN exact_values AS value ON value.value_id = share.share_value_id "
        "WHERE share.assertion_id = ? ORDER BY share.party_id",
        (assertion_id,),
    )
    return [
        {
            "party_id": party,
            "share_value_id": value,
            "share": {"coefficient": coefficient, "scale": scale},
        }
        for party, value, coefficient, scale in rows
    ]


def _amounts(shares: list[OwnershipShare]) -> tuple[ShareAmount, ShareAmount | None]:
    scale = max((share["share"]["scale"] for share in shares), default=0)
    coefficient = sum(
        int(share["share"]["coefficient"]) * 10 ** (scale - share["share"]["scale"])
        for share in shares
    )
    remainder = 10**scale - coefficient
    return (
        {"coefficient": str(coefficient), "scale": scale},
        {"coefficient": str(remainder), "scale": scale} if remainder >= 0 else None,
    )


def _evidence(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, parse_constant=_reject_json_constant)
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("Ownership evidence is not a valid JSON object.") from exc
    if not isinstance(value, dict):
        raise RepositoryIntegrityError("Ownership evidence is not a valid JSON object.")
    return value


def _assertions(
    connection: sqlite3.Connection, account_id: str, as_of: str
) -> list[OwnershipAssertion]:
    rows = connection.execute(
        "SELECT assertion_id, confirmation_state, completeness, effective_from, effective_to, "
        "supersedes_assertion_id, unknown_remainder, evidence_json FROM ownership_assertion_sets "
        "WHERE account_id = ? AND (effective_from IS NULL OR effective_from <= ?) "
        "AND (effective_to IS NULL OR effective_to >= ?) ORDER BY assertion_id",
        (account_id, as_of, as_of),
    ).fetchall()
    result: list[OwnershipAssertion] = []
    for identifier, confirmation, completeness, start, end, previous, unknown, evidence in rows:
        shares = _shares(connection, identifier)
        total, remainder = _amounts(shares)
        successors = connection.execute(
            "SELECT assertion_id FROM ownership_assertion_sets "
            "WHERE supersedes_assertion_id = ? AND confirmation_state = 'confirmed' "
            "ORDER BY assertion_id",
            (identifier,),
        )
        result.append(
            {
                "assertion_id": identifier,
                "evidence": _evidence(evidence),
                "confirmation_state": confirmation,
                "completeness": completeness,
                "effective_from": start,
                "effective_to": end,
                "supersedes_assertion_id": previous,
                "superseded_by": [row[0] for row in successors],
                "unknown_remainder": bool(unknown),
                "shares": shares,
                "total": total,
                "remainder": remainder,
            }
        )
    return result


def ownership_projection(
    connection: sqlite3.Connection, account_id: str, *, as_of: str
) -> OwnershipProjection:
    """Read one account's detached ownership from the caller's stable snapshot.

    Bounds include both endpoints. A confirmed successor retires its predecessor
    globally, exactly as the canonical overlap validator does; querying an earlier
    date does not resurrect corrected evidence. Unconfirmed/rejected assertions
    remain evidence only. ``remainder`` measures unassigned ownership, not a party.
    """
    validate_entity_id(account_id)
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("Ownership as-of must be a canonical ISO date.")
    if (
        connection.execute("SELECT 1 FROM accounts WHERE entity_id = ?", (account_id,)).fetchone()
        is None
    ):
        raise RepositoryIntegrityError("Requested ownership account does not exist.")
    _validate_ownership_assertions(connection)
    assertions = _assertions(connection, account_id, as_of)
    active = [
        assertion
        for assertion in assertions
        if assertion["confirmation_state"] == "confirmed" and not assertion["superseded_by"]
    ]
    if len(active) > 1:
        raise RepositoryIntegrityError("Active confirmed ownership assertions overlap.")
    result: OwnershipProjection = {
        "account_id": account_id,
        "as_of": as_of,
        "status": "unconfirmed"
        if any(
            assertion["confirmation_state"] == "unconfirmed" and not assertion["superseded_by"]
            for assertion in assertions
        )
        else "unknown",
        "assertion_id": None,
        "completeness": "unknown",
        "unknown_remainder": True,
        "shares": [],
        "remainder": {"coefficient": "1", "scale": 0},
        "assertions": assertions,
    }
    if active:
        selected = active[0]
        remainder = selected["remainder"]
        if remainder is None:
            raise RepositoryIntegrityError("Confirmed ownership shares exceed one.")
        result["status"] = "confirmed"
        result["assertion_id"] = selected["assertion_id"]
        result["completeness"] = selected["completeness"]
        result["unknown_remainder"] = selected["unknown_remainder"]
        result["shares"] = deepcopy(selected["shares"])
        result["remainder"] = deepcopy(remainder)
    return result
