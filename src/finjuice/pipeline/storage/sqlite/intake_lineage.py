"""Validated immutable parent/successor links embedded in existing intake evidence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from finjuice.pipeline.storage.sqlite.errors import (
    MutationValidationError,
    RepositoryIntegrityError,
)


def proposal_target(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    if set(payload) != {"change_kind", "operation", "decision"} or not isinstance(
        payload["decision"], dict
    ):
        raise MutationValidationError("A revision needs the typed proposal envelope.")
    kind, operation, decision = payload["change_kind"], payload["operation"], payload["decision"]
    try:
        if (kind, operation) == ("account_fact", "account_binding"):
            return kind, operation, decision["source_namespace"], decision["external_key"]
        if (kind, operation) == ("account_fact", "ownership"):
            return kind, operation, decision["account_id"]
        if (kind, operation) == ("account_fact", "asset_observation"):
            return (
                kind,
                operation,
                decision["account_id"],
                decision["resource_id"],
                decision["field"],
                decision.get("row_index"),
            )
        if (kind, operation) == ("account_fact", "asset_meaning"):
            return kind, operation, decision["source_entity_id"], decision["account_id"]
        if (kind, operation) == ("transaction_override", "manual_transaction"):
            return kind, operation, decision["identifier"]
        if (kind, operation) == ("recurring_rule", "rule"):
            name = decision["rule"]["name"] if decision["action"] == "upsert" else decision["name"]
            return kind, operation, name
    except (KeyError, TypeError) as exc:
        raise MutationValidationError("Revision target identity is missing.") from exc
    raise MutationValidationError("Unsupported proposal type or operation.")


def validated_lineage(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Verify parent identities, source continuity, decision type and acyclic single successors."""
    records = connection.execute(
        "SELECT p.proposal_id, p.payload_digest, p.extraction_id, p.payload_json, p.command_scope, "
        "o.occurrence_json, a.source_artifact_id, app.changeset_id "
        "FROM agent_intake_proposals p JOIN agent_intake_extractions e "
        "ON e.extraction_id=p.extraction_id "
        "JOIN agent_intake_occurrences o ON o.occurrence_id=e.occurrence_id "
        "JOIN agent_intake_artifacts a ON a.intake_artifact_id=o.intake_artifact_id "
        "LEFT JOIN agent_intake_applications app ON app.proposal_id=p.proposal_id"
    ).fetchall()
    by_id = {row[0]: row for row in records}
    links = {}
    children = set()
    try:
        for row in records:
            detail = json.loads(row[5])
            if "proposal_revision" not in detail:
                continue
            link = detail["proposal_revision"]
            if not isinstance(link, dict) or set(link) != {
                "parent_proposal_id",
                "parent_payload_digest",
                "parent_extraction_id",
                "parent_application_changeset_id",
                "evidence",
                "resolved_uncertainties",
            }:
                raise ValueError("Malformed revision evidence.")
            parent_id = link["parent_proposal_id"]
            parent = by_id[parent_id]
            if parent_id in children or parent_id == row[0]:
                raise ValueError("Intake revision branches or self-references.")
            if (
                link["parent_payload_digest"],
                link["parent_extraction_id"],
                link["parent_application_changeset_id"],
                row[4],
                row[6],
            ) != (parent[1], parent[2], parent[7], parent[4], parent[6]):
                raise ValueError("Intake parent identity or original source changed.")
            if not isinstance(link["evidence"], dict) or not link["evidence"]:
                raise ValueError("Missing revision evidence.")
            if proposal_target(json.loads(row[3])) != proposal_target(json.loads(parent[3])):
                raise ValueError("Intake revision changes the decision type or target.")
            children.add(parent_id)
            links[row[0]] = link
        _validate_acyclic(links)
    except (ValueError, TypeError, KeyError) as exc:
        raise RepositoryIntegrityError("Intake revision evidence is inconsistent.") from exc
    return links


def _validate_acyclic(links: Mapping[str, Mapping[str, Any]]) -> None:
    for identifier in links:
        seen = set()
        current = identifier
        while current in links:
            if current in seen:
                raise ValueError("Intake revision lineage cycles.")
            seen.add(current)
            current = links[current]["parent_proposal_id"]
