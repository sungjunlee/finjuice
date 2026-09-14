"""One-snapshot asset meaning, inclusion and explicitly scoped household reporting."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations
from typing import Any, Literal, Mapping

from finjuice.pipeline.assets.money import exact_add, exact_multiply
from finjuice.pipeline.storage.sqlite.asset_meanings import _date, _evidence, asset_sources, rows
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id

STOCK = {"balance", "valuation", "right_obligation"}


@dataclass(frozen=True)
class AssetRelationDecision:
    container_id: str
    member_id: str
    relation_kind: Literal["includes", "overlaps"]
    evidence: Mapping[str, Any]
    confirmation_state: Literal["confirmed", "unconfirmed", "rejected"] = "confirmed"
    effective_from: str | None = None
    effective_to: str | None = None
    supersedes_assertion_id: str | None = None


@dataclass(frozen=True)
class AssetReportQuery:
    as_of: str
    valuation_currency: str
    party_ids: tuple[str, ...]
    source_ids: tuple[str, ...] = ()
    stale_days: int = 30


def validate_asset_relation(connection: sqlite3.Connection, command: AssetRelationDecision) -> None:
    """Require real source endpoints and preserve the endpoint pair when correcting."""
    sources = asset_sources(connection)
    if (
        command.container_id == command.member_id
        or not {command.container_id, command.member_id} <= sources.keys()
    ):
        raise MutationValidationError(
            "Inclusion endpoints must be distinct canonical asset sources."
        )
    if command.relation_kind not in {"includes", "overlaps"}:
        raise MutationValidationError("Asset relation must explicitly include or overlap.")
    _evidence(command.evidence)
    if command.supersedes_assertion_id:
        previous = connection.execute(
            "SELECT subject_entity_id, object_entity_id FROM entity_relation_assertions "
            "WHERE assertion_id = ?",
            (command.supersedes_assertion_id,),
        ).fetchone()
        if previous is None or tuple(previous) != (command.container_id, command.member_id):
            raise MutationValidationError(
                "Asset relation correction must retain its endpoint pair."
            )
        if connection.execute(
            "SELECT 1 FROM entity_relation_assertions WHERE supersedes_assertion_id = ?",
            (command.supersedes_assertion_id,),
        ).fetchone():
            raise MutationConflictError("Asset relation was already corrected.")


def _heads(meanings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["assertion_id"]: row for row in meanings}
    superseded: set[str] = set()
    for row in meanings:
        if row["confirmation_state"] != "confirmed":
            continue
        previous = row["supersedes_assertion_id"]
        seen: set[str] = set()
        while previous is not None and previous in by_id and previous not in seen:
            superseded.add(previous)
            seen.add(previous)
            previous = by_id[previous]["supersedes_assertion_id"]
    return [row for row in meanings if row["assertion_id"] not in superseded]


def asset_candidates(connection: sqlite3.Connection) -> dict[str, Any]:
    """Expose source identity/state and all meaning evidence without confirming legacy facts."""
    sources = asset_sources(connection)
    meanings = rows(connection, "asset_meaning_assertions")
    interpreted = {row["source_entity_id"] for row in _heads(meanings)}
    return {
        "sources": list(sources.values()),
        "meaning_assertions": meanings,
        "relations": rows(connection, "entity_relation_assertions"),
        "pending": [
            {"source_entity_id": key, "reason": "meaning_unconfirmed"}
            for key in sources
            if key not in interpreted
        ],
        "legacy_pending": [
            {
                "source_observation_id": row["observation_id"],
                "reason": "legacy_report_not_interpreted",
            }
            for row in rows(connection, "legacy_overview_reports")
        ],
    }


def _exact(row: Mapping[str, Any]) -> Decimal:
    return ExactValue(
        row["coefficient"], row["scale"], None, "number", "calculated", unit="asset_value.v1"
    ).to_decimal()


def _amount(value: Decimal | None) -> dict[str, Any] | None:
    if value is None:
        return None
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    coefficient = "".join(str(digit) for digit in digits)
    if exponent > 0:
        coefficient += "0" * exponent
    if sign and coefficient != "0":
        coefficient = "-" + coefficient
    return {"coefficient": coefficient, "scale": max(-exponent, 0)}


def _issue(kind: str, source_id: str | None, **detail: Any) -> dict[str, Any]:
    return {"kind": kind, "source_entity_id": source_id, **detail}


def _selection(
    meanings: list[dict[str, Any]], query: AssetReportQuery, issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    eligible = []
    for row in meanings:
        if row["as_of"] > query.as_of:
            issues.append(_issue("future_observation", row["source_entity_id"]))
        elif row["confirmation_state"] != "confirmed":
            issues.append(_issue("meaning_" + row["confirmation_state"], row["source_entity_id"]))
        else:
            eligible.append(row)
    selected = [row for row in eligible if row["measure_kind"] not in STOCK | {"holding_quantity"}]
    groups: dict[tuple, list] = {}
    for row in eligible:
        if row["measure_kind"] in STOCK | {"holding_quantity"}:
            groups.setdefault(
                (row["account_id"], row["resource_id"], row["measure_kind"]), []
            ).append(row)
    for group in groups.values():
        complete = [row for row in group if row["scope_state"] == "complete"]
        candidates = complete or group
        latest = max(row["as_of"] for row in candidates)
        winners = [row for row in candidates if row["as_of"] == latest]
        selected.extend(winners)
        for row in group:
            if row not in winners:
                issues.append(
                    _issue(
                        "partial_does_not_replace_complete"
                        if row["scope_state"] != "complete"
                        else "historical_evidence",
                        row["source_entity_id"],
                        blocking=False,
                    )
                )
    return selected


def _active_relations(connection: sqlite3.Connection, as_of: str) -> list[dict[str, Any]]:
    relations = rows(connection, "entity_relation_assertions")
    relations = _heads(relations)
    return [
        row
        for row in relations
        if (row["effective_from"] is None or row["effective_from"] <= as_of)
        and (row["effective_to"] is None or row["effective_to"] >= as_of)
    ]


def _exclusions(
    selected: list[dict[str, Any]], relations: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_id = {row["source_entity_id"]: row for row in selected}
    exclusions = {}
    for relation in relations:
        container, member = relation["subject_entity_id"], relation["object_entity_id"]
        if container not in by_id or member not in by_id:
            continue
        if relation["confirmation_state"] == "confirmed" and relation["relation_kind"] in {
            "includes",
            "overlaps",
        }:
            exclusions[member] = {
                "reason": "included_in_source"
                if relation["relation_kind"] == "includes"
                else "overlaps_source",
                "container_id": container,
                "assertion_id": relation["assertion_id"],
                "evidence": json.loads(relation["evidence_json"]),
            }
        else:
            issues.append(
                _issue("relation_unconfirmed", member, assertion_id=relation["assertion_id"])
            )
    for left, right in combinations(selected, 2):
        a, b = left["source_entity_id"], right["source_entity_id"]
        if a in exclusions or b in exclusions or left["account_id"] != right["account_id"]:
            continue
        if left["measure_kind"] not in STOCK or right["measure_kind"] not in STOCK:
            continue
        if (
            left["resource_id"] != right["resource_id"]
            and left["resource_id"] is not None
            and right["resource_id"] is not None
        ):
            continue
        issues.append(_issue("unresolved_overlap", a, other_source_id=b))
        # Exclude both instead of silently choosing a source or double counting it.
        exclusions[a] = {"reason": "unresolved_overlap", "other_source_id": b}
        exclusions[b] = {"reason": "unresolved_overlap", "other_source_id": a}
    _inclusion_cycles(exclusions, issues)
    return exclusions


def _inclusion_cycles(exclusions: dict[str, dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    # Cyclic inclusion cannot justify removing every supporting source.
    for member, exclusion in list(exclusions.items()):
        seen = {member}
        target = exclusion.get("container_id")
        while target in exclusions and "container_id" in exclusions[target]:
            if target in seen:
                issues.append(_issue("inclusion_cycle", member))
                break
            seen.add(target)
            target = exclusions[target]["container_id"]


def _owned_fraction(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    query: AssetReportQuery,
    issues: list[dict[str, Any]],
) -> Decimal | None:
    from finjuice.pipeline.storage.sqlite.ownership_projection import ownership_projection

    ownership = ownership_projection(connection, row["account_id"], as_of=query.as_of)
    if ownership["status"] != "confirmed":
        issues.append(
            _issue("ownership_unconfirmed", row["source_entity_id"], account_id=row["account_id"])
        )
        return None
    if ownership["unknown_remainder"]:
        issues.append(
            _issue(
                "ownership_unknown_remainder",
                row["source_entity_id"],
                remainder=ownership["remainder"],
            )
        )
    total = Decimal(0)
    for share in ownership["shares"]:
        if share["party_id"] in query.party_ids:
            total = exact_add(total, _exact(share["share"]))
    return total


def _value(
    row: dict[str, Any],
    values: dict[str, dict[str, Any]],
    query: AssetReportQuery,
    issues: list[dict[str, Any]],
) -> Decimal | None:
    original = _exact(values[row["value_id"]])
    currency = row["original_currency"]
    if currency is None:
        issues.append(_issue("original_currency_unknown", row["source_entity_id"]))
        return None
    if currency == query.valuation_currency:
        return original
    if (
        row["fx_value_id"] is None
        or row["fx_quote_currency"] != query.valuation_currency
        or row["fx_as_of"] > query.as_of
    ):
        issues.append(_issue("fx_basis_missing", row["source_entity_id"]))
        return None
    if (
        date.fromisoformat(query.as_of) - date.fromisoformat(row["fx_as_of"])
    ).days > query.stale_days:
        issues.append(_issue("fx_basis_stale", row["source_entity_id"]))
    return exact_multiply(original, _exact(values[row["fx_value_id"]]))


def _validate_query(connection: sqlite3.Connection, query: AssetReportQuery, sources: dict) -> None:
    _date(query.as_of)
    if not query.party_ids or not re.fullmatch(r"[A-Z]{3}", query.valuation_currency):
        raise MutationValidationError(
            "An explicit party UUID set and valuation currency are required."
        )
    if type(query.stale_days) is not int or query.stale_days < 0:
        raise MutationValidationError("stale_days must be a non-negative integer.")
    for party in set(query.party_ids):
        validate_entity_id(party)
        if not connection.execute("SELECT 1 FROM parties WHERE entity_id = ?", (party,)).fetchone():
            raise MutationValidationError("Reporting party does not exist.")
    if not set(query.source_ids) <= sources.keys():
        raise MutationValidationError("Reporting scope contains unknown source entities.")


def asset_report(connection: sqlite3.Connection, query: AssetReportQuery) -> dict[str, Any]:
    """Produce an exact declared-scope total only when every required decision is supported."""
    sources = asset_sources(connection)
    _validate_query(connection, query, sources)
    scope = set(query.source_ids) if query.source_ids else set(sources)
    meanings = [
        row
        for row in _heads(rows(connection, "asset_meaning_assertions"))
        if row["source_entity_id"] in scope
    ]
    issues = [
        _issue("meaning_missing", key)
        for key in sorted(scope - {row["source_entity_id"] for row in meanings})
    ]
    selected = _selection(meanings, query, issues)
    exclusions = _exclusions(selected, _active_relations(connection, query.as_of), issues)
    values = {row["value_id"]: row for row in rows(connection, "exact_values")}
    lines = []
    subtotal = Decimal(0)
    cash = Decimal(0)
    for row in selected:
        source_id = row["source_entity_id"]
        line = {
            "source_entity_id": source_id,
            "assertion_id": row["assertion_id"],
            "account_id": row["account_id"],
            "resource_id": row["resource_id"],
            "measure_kind": row["measure_kind"],
            "as_of": row["as_of"],
            "scope_state": row["scope_state"],
            "source": sources[source_id],
            "original": _amount(_exact(values[row["value_id"]])),
            "original_currency": row["original_currency"],
            "net_worth_sign": row["net_worth_sign"],
            "fx_basis": {
                key: row[key]
                for key in ("fx_value_id", "fx_quote_currency", "fx_as_of", "fx_evidence_json")
            },
            "evidence": json.loads(row["evidence_json"]),
            "contribution": "excluded",
            "valued_share": None,
        }
        line["fx_basis"]["rate"] = (
            _amount(_exact(values[row["fx_value_id"]])) if row["fx_value_id"] else None
        )
        lines.append(line)
        if source_id in exclusions:
            line["exclusion"] = exclusions[source_id]
            continue
        if row["scope_state"] != "complete":
            issues.append(_issue("scope_incomplete", source_id))
        if (
            date.fromisoformat(query.as_of) - date.fromisoformat(row["as_of"])
        ).days > query.stale_days:
            issues.append(_issue("stale", source_id))
        if row["measure_kind"] in {"holding_quantity", "expected_inflow"}:
            if row["measure_kind"] == "holding_quantity":
                issues.append(_issue("valuation_missing", source_id))
            line["contribution"] = row["measure_kind"]
            continue
        fraction = _owned_fraction(connection, row, query, issues)
        amount = _value(row, values, query, issues)
        if amount is None or fraction is None:
            continue
        weighted = exact_multiply(amount, fraction)
        if row["measure_kind"] in STOCK:
            weighted = exact_multiply(weighted, Decimal(row["net_worth_sign"]))
            subtotal = exact_add(subtotal, weighted)
            line["contribution"] = "net_worth"
        else:
            cash = exact_add(cash, weighted)
            line["contribution"] = "cash_movement"
        line["ownership_share"] = _amount(fraction)
        line["valued_share"] = _amount(weighted)
    if not query.source_ids and rows(connection, "legacy_overview_reports"):
        issues.append(_issue("legacy_reports_pending", None))
    complete = bool(selected) and not any(issue.get("blocking", True) for issue in issues)
    return {
        "as_of": query.as_of,
        "stale_days": query.stale_days,
        "party_ids": sorted(set(query.party_ids)),
        "valuation_currency": query.valuation_currency,
        "declared_source_ids": sorted(scope),
        "scope_kind": "explicit_sources" if query.source_ids else "all_canonical_asset_sources",
        "completeness": "complete_for_declared_scope" if complete else "incomplete",
        "net_worth_total": _amount(subtotal) if complete else None,
        "known_net_worth_subtotal": _amount(subtotal),
        "cash_flow_subtotal": _amount(cash),
        "valuation_is_cash_flow": False,
        "lines": lines,
        "issues": issues,
        "worldwide_asset_completeness_claimed": False,
    }
