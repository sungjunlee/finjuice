"""Detached evidence and decision views from one caller-owned SQLite snapshot."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, TypedDict

from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError


class IntakeDecisionView(TypedDict):
    """Repository identity and immutable proposal evidence for an operator."""

    dataset_generation: str
    dataset_revision: int
    decisions: list[dict[str, Any]]


def find_intake_artifact(
    connection: sqlite3.Connection, source_artifact_id: str
) -> dict[str, Any] | None:
    """Find an existing evidence identity within the mutation's locked transaction."""
    row = connection.execute(
        "SELECT intake_artifact_id, media_type, evidence_json, created_at "
        "FROM agent_intake_artifacts WHERE source_artifact_id = ?",
        (source_artifact_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "intake_artifact_id": row[0],
        "media_type": row[1],
        "evidence": json.loads(row[2]),
        "created_at": row[3],
    }


def intake_decision_view(connection: sqlite3.Connection) -> IntakeDecisionView:
    """Read pending/stale/uncertain and applied evidence without changing any decisions.

    The caller must open a repository read transaction before calling. Returned
    JSON values are detached; the caller may close that snapshot afterwards.
    All confirmations remain visible: conflicting decisions are never resolved
    by a last-writer heuristic. This view does not grant application authority.
    """
    if not connection.in_transaction:
        raise ValueError("Intake decisions require a caller-owned read snapshot.")
    meta = connection.execute(
        "SELECT dataset_generation, dataset_revision FROM repository_meta WHERE singleton = 1"
    ).fetchone()
    if meta is None:
        raise RepositoryIntegrityError("Intake snapshot has no repository identity.")
    decisions: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT p.proposal_id, p.command_scope, p.idempotency_key, p.expected_generation, "
        "p.expected_revision, p.policy_version, p.payload_json, p.payload_digest, "
        "e.extraction_id, e.extractor, e.payload_json, o.occurrence_id, o.channel, "
        "o.received_at, o.occurrence_json, a.intake_artifact_id, a.source_artifact_id, "
        "a.media_type FROM agent_intake_proposals p "
        "JOIN agent_intake_extractions e ON e.extraction_id = p.extraction_id "
        "JOIN agent_intake_occurrences o ON o.occurrence_id = e.occurrence_id "
        "JOIN agent_intake_artifacts a ON a.intake_artifact_id = o.intake_artifact_id "
        "ORDER BY p.created_at, p.proposal_id"
    ).fetchall()
    for row in rows:
        confirmations = [
            {
                "confirmation_id": item[0],
                "state": item[1],
                "actor": item[2],
                "detail": json.loads(item[3]),
                "confirmed_at": item[4],
            }
            for item in connection.execute(
                "SELECT confirmation_id, confirmation_state, actor, confirmation_json, "
                "confirmed_at FROM agent_intake_confirmations WHERE proposal_id = ? "
                "ORDER BY confirmed_at, confirmation_id",
                (row[0],),
            )
        ]
        application = connection.execute(
            "SELECT confirmation_id, changeset_id, applied_at FROM agent_intake_applications "
            "WHERE proposal_id = ?",
            (row[0],),
        ).fetchone()
        detail = json.loads(row[14])
        uncertainties = detail.get("uncertainties", [])
        if not isinstance(uncertainties, list) or any(
            not isinstance(item, str) for item in uncertainties
        ):
            uncertainties = ["invalid_uncertainty_evidence"]
        stale = row[3] != meta[0] or row[4] != meta[1]
        states = {item["state"] for item in confirmations}
        if application is not None:
            status = "applied"
        elif len(states) > 1:
            status = "conflicting_confirmations"
        elif "rejected" in states:
            status = "rejected"
        elif stale:
            status = "stale"
        elif uncertainties:
            status = "uncertain"
        elif "confirmed" in states:
            status = "confirmed_unapplied"
        else:
            status = "pending"
        decisions.append(
            {
                "proposal_id": row[0],
                "application_scope": row[1],
                "application_key": row[2],
                "expected_generation": row[3],
                "expected_revision": row[4],
                "policy_version": row[5],
                "proposal": json.loads(row[6]),
                "payload_digest": row[7],
                "extraction_id": row[8],
                "extractor": row[9],
                "extraction": json.loads(row[10]),
                "occurrence_id": row[11],
                "channel": row[12],
                "received_at": row[13],
                "occurrence": detail,
                "intake_artifact_id": row[15],
                "source_artifact_id": row[16],
                "media_type": row[17],
                "status": status,
                "stale": stale,
                "uncertainties": uncertainties,
                "confirmations": confirmations,
                "application": None
                if application is None
                else {
                    "confirmation_id": application[0],
                    "changeset_id": application[1],
                    "applied_at": application[2],
                },
            }
        )
    return {
        "dataset_generation": str(meta[0]),
        "dataset_revision": int(meta[1]),
        "decisions": decisions,
    }
