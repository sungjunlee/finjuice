"""Durable common evidence intake through the canonical mutation boundary."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationContext,
    MutationOutcome,
    MutationReceipt,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import (
    AgentIntakeArtifactRecord,
    AgentIntakeExtractionRecord,
    AgentIntakeOccurrenceRecord,
    AgentIntakeProposalRecord,
)


@dataclass(frozen=True)
class IntakeSubmission:
    """Original bytes and independent extraction/proposal supplied by a producer.

    A proposal may use ``change_kind``, ``operation``, and ``decision`` keys.
    It is stored unchanged for a later typed application handler; submission
    never executes it. Uncertainties belong to the receipt occurrence.
    ``expected_revision`` precedes submission, while the returned proposal
    revision identifies the repository immediately after submission.
    """

    source_kind: Literal["description", "screenshot", "xlsx"]
    content: bytes
    media_type: str
    channel: str
    received_at: str
    extractor: str
    extraction: Mapping[str, Any] | list[Any]
    proposal_scope: str
    proposal: Mapping[str, Any]
    policy_version: str
    idempotency_key: str
    expected_generation: str
    expected_revision: int
    actor: str
    uncertainties: tuple[str, ...] = ()


def submit_intake(service: MutationService, submission: IntakeSubmission) -> MutationReceipt:
    """Capture exact evidence and append a proposal atomically, deduplicating retries."""
    payload = _payload(submission)
    identity = hashlib.sha256(
        _json([submission.proposal_scope, submission.idempotency_key]).encode()
    ).hexdigest()
    application_key = "intake.apply." + identity
    request = MutationRequest(
        command_scope="agent.intake.submit",
        idempotency_key=identity,
        payload=payload,
        expected_generation=submission.expected_generation,
        expected_revision=submission.expected_revision,
        actor=submission.actor,
    )

    def capture(context: MutationContext) -> MutationOutcome:
        # execute owns the authority shared lease and BEGIN IMMEDIATE here.
        artifact = SourceObjectStore(context.authority.paths).publish(
            io.BytesIO(submission.content)
        )
        context.register_source_artifact(artifact)
        existing = context.find_intake_artifact(artifact.artifact_id)
        artifact_id = (
            str(existing["intake_artifact_id"])
            if existing is not None
            else _id("artifact/" + artifact.artifact_id)
        )
        if existing is None:
            context.add_intake_artifact(
                AgentIntakeArtifactRecord(
                    artifact_id,
                    artifact.artifact_id,
                    submission.media_type,
                    {"source_digest": artifact.artifact_id},
                    submission.received_at,
                )
            )
        occurrence_id = _id("occurrence/" + identity)
        extraction_id = _id("extraction/" + identity)
        proposal_id = _id("proposal/" + identity)
        context.add_intake_occurrence(
            AgentIntakeOccurrenceRecord(
                occurrence_id,
                artifact_id,
                submission.channel,
                submission.received_at,
                {
                    "source_kind": submission.source_kind,
                    "media_type": submission.media_type,
                    "uncertainties": payload["uncertainties"],
                },
            )
        )
        context.add_intake_extraction(
            AgentIntakeExtractionRecord(
                extraction_id,
                occurrence_id,
                submission.extractor,
                payload["extraction"],
                submission.received_at,
            )
        )
        context.add_intake_proposal(
            AgentIntakeProposalRecord(
                proposal_id,
                extraction_id,
                submission.policy_version,
                submission.proposal_scope,
                application_key,
                submission.expected_generation,
                submission.expected_revision + 1,
                payload["proposal"],
                submission.received_at,
            )
        )
        return MutationOutcome(
            {
                "source_artifact_id": artifact.artifact_id,
                "intake_artifact_id": artifact_id,
                "occurrence_id": occurrence_id,
                "extraction_id": extraction_id,
                "proposal_id": proposal_id,
                "application_scope": submission.proposal_scope,
                "application_key": application_key,
                "expected_generation": submission.expected_generation,
                "expected_revision": submission.expected_revision + 1,
            },
            retained_artifacts=(artifact.artifact_id,),
        )

    return service.execute(request, capture)


def _payload(submission: IntakeSubmission) -> dict[str, Any]:
    if submission.source_kind not in {"description", "screenshot", "xlsx"}:
        raise MutationValidationError("Intake source kind is unsupported.")
    if not isinstance(submission.content, bytes) or not submission.content:
        raise MutationValidationError("Intake requires nonempty original bytes.")
    if submission.source_kind == "description":
        try:
            submission.content.decode("utf-8")
        except UnicodeDecodeError:
            raise MutationValidationError("Description evidence must be UTF-8 bytes.") from None
    for value in (
        submission.media_type,
        submission.channel,
        submission.received_at,
        submission.extractor,
        submission.proposal_scope,
        submission.policy_version,
        submission.idempotency_key,
    ):
        if not isinstance(value, str) or not value.strip():
            raise MutationValidationError("Intake identity fields must be nonempty text.")
    if not isinstance(submission.proposal, Mapping) or not isinstance(
        submission.extraction, (Mapping, list)
    ):
        raise MutationValidationError("Intake extraction and proposal must be structured JSON.")
    if any(not isinstance(item, str) or not item for item in submission.uncertainties):
        raise MutationValidationError("Intake uncertainties must be nonempty text.")
    return cast(
        dict[str, Any],
        json.loads(
            _json(
                {
                    "source_kind": submission.source_kind,
                    "source_digest": hashlib.sha256(submission.content).hexdigest(),
                    "media_type": submission.media_type,
                    "channel": submission.channel,
                    "received_at": submission.received_at,
                    "extractor": submission.extractor,
                    "extraction": submission.extraction,
                    "proposal_scope": submission.proposal_scope,
                    "proposal": submission.proposal,
                    "policy_version": submission.policy_version,
                    "uncertainties": list(submission.uncertainties),
                }
            )
        ),
    )


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise MutationValidationError("Intake payload must be finite JSON data.") from None


def _id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "finjuice/intake/" + value))
