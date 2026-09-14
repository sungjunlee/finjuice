"""Canonical immutable monthly close revisions, reopen lineage and explicit diffs.

A close freezes the exact facts that produced it: the pinned dataset revision,
rules/config identity, the caller-declared calculation policy, source as-of and
asset scope, the unresolved facts observed at freeze time, and exact per-currency
totals. Totals are never summed across currencies and an unknown currency is
reported as an unresolved fact instead of being folded into a guessed total.
Late input or changed rules never rewrite a stored close: the period must be
explicitly reopened and reclosed, which appends a successor revision carrying an
explicit diff against its predecessor.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from finjuice.pipeline.assets.money import exact_add
from finjuice.pipeline.storage.sqlite.asset_reports import AssetReportQuery, asset_report
from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationValidationError,
    RepositoryIntegrityError,
)
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.schema_v9 import TABLE_KEYS

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.mutations import MutationContext

ASSET_SCOPES = ("transactions_only", "transactions_and_asset_snapshots")
_BUCKETS = ("income", "expense", "transfer", "other")
_NET_BUCKETS = ("income", "expense", "other")
CALCULATION_POLICY = "cash.v1"
_FACT_KEYS = ("transaction_count", "totals", "unresolved", "completeness", "inputs")
_DIFF_FIELDS = (
    "dataset_revision",
    "rules_identity",
    "config_identity",
    "calculation_policy",
    "asset_scope",
    "source_as_of",
    "completeness",
    "unresolved",
    "transaction_count",
    "totals",
)


@dataclass(frozen=True)
class CloseCommand:
    """One caller-specified month close with explicit policy and as-of identity."""

    period: str
    source_as_of: str
    calculation_policy: str
    closed_at: str
    reason: str
    asset_scope: str = "transactions_only"
    party_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    valuation_currency: str | None = None


@dataclass(frozen=True)
class ReopenCommand:
    """An explicit reopen of the newest close revision of one period."""

    period: str
    reason: str
    reopened_at: str


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "finjuice/close/" + value))


def _text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MutationValidationError("Explicit nonempty close text is required.")


def _time(value: str) -> None:
    _text(value)
    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise MutationValidationError("Close timestamps require an explicit timezone.")


def _period(value: str) -> str:
    _text(value)
    if len(value) != 7 or date.fromisoformat(value + "-01").strftime("%Y-%m") != value:
        raise MutationValidationError("Close period must be an exact YYYY-MM month.")
    return value


def _amount(coefficient: str, scale: int) -> Decimal:
    return ExactValue(
        coefficient, int(scale), None, "number", "calculated", unit="close_value.v1"
    ).to_decimal()


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table not in TABLE_KEYS:
        raise ValueError("Unsupported close table.")
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {', '.join(TABLE_KEYS[table])}")
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def _insert(
    connection: sqlite3.Connection, context: MutationContext, table: str, record: dict[str, Any]
) -> None:
    connection.execute(
        f"INSERT INTO {table} ({', '.join(record)}) VALUES ({', '.join('?' for _ in record)})",
        tuple(record.values()),
    )
    identity = "/".join(str(record[key]) for key in TABLE_KEYS[table])
    context._record(table, identity, "insert", None, record)


def config_identity(connection: sqlite3.Connection) -> dict[str, str]:
    """Read the authoritative configuration head identity pinned by this close."""
    return {
        str(kind): str(revision)
        for kind, revision in connection.execute(
            "SELECT config_kind, revision_id FROM config_heads ORDER BY config_kind"
        )
    }


_TRANSACTION_SQL = """
SELECT t.entity_id, t.type_norm, t.needs_review, t.is_transfer, t.is_transfer_candidate,
       t.timezone_state, t.date_raw, e.coefficient, e.scale, m.currency_code, m.currency_unknown
FROM transactions t
JOIN money_values m ON m.value_id = t.amount_value_id
JOIN exact_values e ON e.value_id = t.amount_value_id
WHERE substr(t.date_raw, 1, 7) = ?
ORDER BY t.entity_id
"""


def _period_end(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    following = date(year + month // 12, month % 12 + 1, 1)
    return (following - timedelta(days=1)).isoformat()


def _bucket_totals(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    totals: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        if row["currency_unknown"]:
            continue
        currency = str(row["currency_code"])
        bucket = "transfer" if row["is_transfer"] == 1 else str(row["type_norm"])
        entry = totals.setdefault(currency, {name: Decimal("0") for name in _BUCKETS})
        entry[bucket] = exact_add(entry[bucket], _amount(row["coefficient"], row["scale"]))
    return {currency: _render_bucket(entry) for currency, entry in sorted(totals.items())}


def _render_bucket(entry: Mapping[str, Decimal]) -> dict[str, str]:
    net = Decimal("0")
    for name in _NET_BUCKETS:
        net = exact_add(net, entry[name])
    rendered = {name: _decimal_text(entry[name]) for name in _BUCKETS}
    rendered["net"] = _decimal_text(net)
    return rendered


def _asset_totals(connection: sqlite3.Connection, command: CloseCommand) -> dict[str, Any]:
    if not command.party_ids or command.valuation_currency is None:
        raise MutationValidationError(
            "Asset close requires explicit party IDs and valuation currency."
        )
    return asset_report(
        connection,
        AssetReportQuery(
            as_of=_period_end(command.period),
            valuation_currency=command.valuation_currency,
            party_ids=command.party_ids,
            source_ids=command.source_ids,
        ),
    )


def _reconciliation_inputs(connection: sqlite3.Connection, period: str) -> list[dict[str, Any]]:
    cursor = connection.execute(
        "SELECT e.evidence_id, a.allocation_id, a.status FROM reconcile_evidence e "
        "LEFT JOIN reconcile_allocation_evidence m ON m.evidence_id=e.evidence_id "
        "AND NOT EXISTS(SELECT 1 FROM reconcile_withdrawals w "
        "WHERE w.allocation_id=m.allocation_id) "
        "LEFT JOIN reconcile_allocations a ON a.allocation_id=m.allocation_id "
        "WHERE e.settlement_unit=1 AND substr(e.occurred_on,1,7)=? ORDER BY e.evidence_id",
        (period,),
    )
    return [{"evidence_id": row[0], "allocation_id": row[1], "status": row[2]} for row in cursor]


def _unresolved(
    rows: Sequence[Mapping[str, Any]],
    assets: Mapping[str, Any] | None,
    period: str,
    reconciliation: Sequence[Mapping[str, Any]] = (),
) -> dict[str, int]:
    edges = {period + "-01", _period_end(period)}
    counted = {
        "reconcile_unmatched": sum(1 for row in reconciliation if row["status"] is None),
        "reconcile_partial": sum(1 for row in reconciliation if row["status"] == "partial"),
        "currency_unknown": sum(1 for row in rows if row["currency_unknown"]),
        "needs_review": sum(1 for row in rows if row["needs_review"] == 1),
        "transfer_undecided": sum(
            1 for row in rows if row["is_transfer"] is None and row["is_transfer_candidate"] == 1
        ),
        "boundary_timezone_unknown": sum(
            1
            for row in rows
            if row["timezone_state"] == "unknown" and str(row["date_raw"])[:10] in edges
        ),
    }
    if assets is not None:
        counted["asset_unresolved"] = len(assets["issues"])
        if assets["completeness"] != "complete_for_declared_scope":
            counted["asset_incomplete"] = 1
    return {name: count for name, count in counted.items() if count}


def compute_close_facts(
    connection: sqlite3.Connection,
    period: str,
    asset_scope: str,
    command: CloseCommand | None = None,
) -> dict[str, Any]:
    """Compute exact per-currency totals and unresolved facts from pinned canonical rows."""
    cursor = connection.execute(_TRANSACTION_SQL, (period,))
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, row, strict=True)) for row in cursor]
    if asset_scope == ASSET_SCOPES[1] and command is None:
        raise MutationValidationError("Explicit asset close scope is required.")
    assets = (
        _asset_totals(connection, command) if command and asset_scope == ASSET_SCOPES[1] else None
    )
    reconciliation = _reconciliation_inputs(connection, period)
    unresolved = _unresolved(rows, assets, period, reconciliation)
    totals: dict[str, Any] = {"transactions": _bucket_totals(rows)}
    if assets is not None:
        totals["asset_snapshots"] = assets
    return {
        "transaction_count": len(rows),
        "inputs": {"transactions": rows, "assets": assets, "reconciliation": reconciliation},
        "totals": totals,
        "unresolved": unresolved,
        "completeness": "incomplete" if unresolved else "complete",
    }


def _head(connection: sqlite3.Connection, period: str) -> dict[str, Any] | None:
    rows = [row for row in _rows(connection, "close_revisions") if row["period"] == period]
    return max(rows, key=lambda row: int(row["close_revision"])) if rows else None


def _reopened(connection: sqlite3.Connection, close_id: str) -> dict[str, Any] | None:
    rows = [row for row in _rows(connection, "close_reopenings") if row["close_id"] == close_id]
    return rows[0] if rows else None


def _identity_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_revision": int(record["dataset_revision"]),
        "rules_identity": str(record["rules_identity"]),
        "config_identity": json.loads(str(record["config_identity_json"])),
        "calculation_policy": str(record["calculation_policy"]),
        "asset_scope": str(record["asset_scope"]),
        "source_as_of": str(record["source_as_of"]),
        "completeness": str(record["completeness"]),
        "unresolved": json.loads(str(record["unresolved_json"])),
        "transaction_count": int(json.loads(str(record["report_json"]))["transaction_count"]),
        "totals": json.loads(str(record["totals_json"])),
    }


def _diff(previous: Mapping[str, Any] | None, current: Mapping[str, Any], reason: str) -> list[Any]:
    if previous is None:
        return [{"field": "close", "change": "initial", "reason": reason}]
    before = _identity_payload(previous)
    changes = [
        {"field": field, "previous": before[field], "current": current[field], "reason": reason}
        for field in _DIFF_FIELDS
        if before[field] != current[field]
    ]
    return changes or [{"field": "close", "change": "unchanged", "reason": reason}]


def _report(command: CloseCommand, revision: int, facts: Mapping[str, Any], **pins: Any) -> dict:
    return {
        "period": command.period,
        "close_revision": revision,
        "calculation_policy": command.calculation_policy,
        "asset_scope": command.asset_scope,
        "source_as_of": command.source_as_of,
        **pins,
        **{key: facts[key] for key in _FACT_KEYS},
    }


def close_period(
    connection: sqlite3.Connection, context: MutationContext, command: CloseCommand
) -> dict[str, Any]:
    """Freeze one immutable close revision; a still-closed period requires an explicit reopen."""
    period = _period(command.period)
    _time(command.source_as_of)
    _time(command.closed_at)
    if command.calculation_policy != CALCULATION_POLICY:
        raise MutationValidationError("Unsupported close calculation policy; use cash.v1.")
    _text(command.reason)
    if command.asset_scope not in ASSET_SCOPES:
        raise MutationValidationError("Close asset scope must be explicitly supported.")
    head = _head(connection, period)
    if head is not None and _reopened(connection, str(head["close_id"])) is None:
        raise MutationConflictError("Period is closed; reopen it before recording a new close.")
    return _append_close(connection, context, command, head)


def _append_close(
    connection: sqlite3.Connection,
    context: MutationContext,
    command: CloseCommand,
    head: Mapping[str, Any] | None,
) -> dict[str, Any]:
    revision = int(head["close_revision"]) + 1 if head else 1
    dataset_revision = int(
        connection.execute("SELECT dataset_revision FROM repository_meta").fetchone()[0]
    )
    identity = config_identity(connection)
    facts = compute_close_facts(connection, command.period, command.asset_scope, command)
    pins = {
        "dataset_revision": dataset_revision,
        "rules_identity": identity.get("rules", "absent"),
        "config_identity": identity,
    }
    report = _report(command, revision, facts, **pins)
    diff = _diff(head, {**pins, **_scalar_facts(command, facts)}, command.reason)
    record = _record(command, revision, head, report, diff, facts, pins, context.changeset_id)
    _insert(connection, context, "close_revisions", record)
    return {
        "close": report,
        "close_id": record["close_id"],
        "report_digest": record["report_digest"],
        "diff": diff,
        "reclosed": head is not None,
    }


def _scalar_facts(command: CloseCommand, facts: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "calculation_policy": command.calculation_policy,
        "asset_scope": command.asset_scope,
        "source_as_of": command.source_as_of,
        "completeness": facts["completeness"],
        "unresolved": facts["unresolved"],
        "transaction_count": facts["transaction_count"],
        "totals": facts["totals"],
    }


def _record(
    command: CloseCommand,
    revision: int,
    head: Mapping[str, Any] | None,
    report: Mapping[str, Any],
    diff: list[Any],
    facts: Mapping[str, Any],
    pins: Mapping[str, Any],
    changeset_id: str,
) -> dict[str, Any]:
    payload = _json(report)
    return {
        "close_id": _id(_json([command.period, revision])),
        "period": command.period,
        "close_revision": revision,
        "predecessor_close_id": str(head["close_id"]) if head else None,
        "dataset_revision": int(pins["dataset_revision"]),
        "rules_identity": str(pins["rules_identity"]),
        "config_identity_json": _json(pins["config_identity"]),
        "calculation_policy": command.calculation_policy,
        "asset_scope": command.asset_scope,
        "source_as_of": command.source_as_of,
        "completeness": str(facts["completeness"]),
        "unresolved_json": _json(facts["unresolved"]),
        "totals_json": _json(facts["totals"]),
        "report_json": payload,
        "report_digest": hashlib.sha256(payload.encode("ascii")).hexdigest(),
        "diff_json": _json(diff),
        "closed_at": command.closed_at,
        "created_changeset_id": changeset_id,
    }


def reopen_period(
    connection: sqlite3.Connection, context: MutationContext, command: ReopenCommand
) -> dict[str, Any]:
    """Append an explicit reopen; stored close revisions and later transactions stay intact."""
    period = _period(command.period)
    _text(command.reason)
    _time(command.reopened_at)
    head = _head(connection, period)
    if head is None:
        raise MutationConflictError("Period has no close revision to reopen.")
    close_id = str(head["close_id"])
    if _reopened(connection, close_id) is not None:
        raise MutationConflictError("Close revision is already reopened.")
    record = {
        "reopen_id": _id(_json(["reopen", close_id])),
        "close_id": close_id,
        "reason": command.reason,
        "reopened_at": command.reopened_at,
        "created_changeset_id": context.changeset_id,
    }
    _insert(connection, context, "close_reopenings", record)
    return {"close_id": close_id, "period": period, "close_revision": int(head["close_revision"])}


def regenerate_report(record: Mapping[str, Any]) -> dict[str, Any]:
    """Recalculate a historical report from its immutable captured facts, not live rows."""
    stored = json.loads(str(record["report_json"]))
    if stored["calculation_policy"] != CALCULATION_POLICY:
        raise RepositoryIntegrityError("Stored close uses an unsupported calculation policy.")
    inputs = stored["inputs"]
    rows, assets = inputs["transactions"], inputs["assets"]
    unresolved = _unresolved(rows, assets, stored["period"], inputs["reconciliation"])
    totals: dict[str, Any] = {"transactions": _bucket_totals(rows)}
    if assets is not None:
        totals["asset_snapshots"] = assets
    report = {
        **stored,
        "totals": totals,
        "transaction_count": len(rows),
        "unresolved": unresolved,
        "completeness": "incomplete" if unresolved else "complete",
    }
    if (
        _json(report) != _json(stored)
        or hashlib.sha256(_json(report).encode("ascii")).hexdigest() != record["report_digest"]
        or _json(totals) != record["totals_json"]
        or _json(unresolved) != record["unresolved_json"]
    ):
        raise RepositoryIntegrityError(
            "Stored close report differs from its captured facts or digest."
        )
    return report


def close_view(connection: sqlite3.Connection, *, period: str | None = None) -> dict[str, Any]:
    """Read the full immutable close history and current period state from one snapshot."""
    reopenings = {row["close_id"]: row for row in _rows(connection, "close_reopenings")}
    revisions = [
        {
            "close_id": row["close_id"],
            "period": row["period"],
            "close_revision": int(row["close_revision"]),
            "predecessor_close_id": row["predecessor_close_id"],
            "report": regenerate_report(row),
            "report_digest": row["report_digest"],
            "diff": json.loads(str(row["diff_json"])),
            "closed_at": row["closed_at"],
            "reopened": _reopen_payload(reopenings.get(row["close_id"])),
        }
        for row in _rows(connection, "close_revisions")
        if period is None or row["period"] == period
    ]
    revisions.sort(key=lambda item: (item["period"], item["close_revision"]))
    return {"revisions": revisions, "periods": _period_states(revisions)}


def _reopen_payload(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"reason": str(row["reason"]), "reopened_at": str(row["reopened_at"])}


def _period_states(revisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    states: dict[str, Any] = {}
    for item in revisions:
        states[str(item["period"])] = {
            "state": "reopened" if item["reopened"] else "closed",
            "close_revision": int(item["close_revision"]),
            "completeness": item["report"]["completeness"],
            "report_digest": item["report_digest"],
        }
    return states


def validate_close(connection: sqlite3.Connection) -> None:
    """Reject broken close lineage, duplicated revisions or reopen without a close."""
    revisions = _rows(connection, "close_revisions")
    by_period: dict[str, list[dict[str, Any]]] = {}
    for row in revisions:
        regenerate_report(row)
        by_period.setdefault(str(row["period"]), []).append(row)
    for rows in by_period.values():
        ordered = sorted(rows, key=lambda row: int(row["close_revision"]))
        if [int(row["close_revision"]) for row in ordered] != list(range(1, len(ordered) + 1)):
            raise RepositoryIntegrityError("Close revisions are not contiguous for a period.")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current["predecessor_close_id"] != previous["close_id"]:
                raise RepositoryIntegrityError("Close revision lineage is broken.")
    known = {str(row["close_id"]) for row in revisions}
    if any(str(row["close_id"]) not in known for row in _rows(connection, "close_reopenings")):
        raise RepositoryIntegrityError("A reopen references an unknown close revision.")
