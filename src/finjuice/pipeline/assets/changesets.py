"""Meaning corrections as explicit changesets. Observations stay immutable."""

from __future__ import annotations

from dataclasses import replace

from finjuice.pipeline.assets.models import (
    ConfirmationState,
    CorrectionOp,
    InclusionAssertion,
    MeaningChangeset,
    Observation,
    ObservationBundle,
)


class RevisionConflictError(ValueError):
    """Raised when a changeset expected_revision does not match the bundle."""


def apply_changeset(
    bundle: ObservationBundle,
    changeset: MeaningChangeset,
) -> ObservationBundle:
    """Return a new bundle with the changeset applied. Never mutates inputs."""
    if changeset.expected_revision != bundle.revision:
        raise RevisionConflictError(
            "Meaning correction expected_revision does not match the bundle revision."
        )
    if not changeset.operations:
        raise ValueError("Meaning changeset requires at least one operation.")
    observations = list(bundle.observations)
    inclusions = list(bundle.inclusions)
    for operation in changeset.operations:
        observations, inclusions = _apply_operation(observations, inclusions, operation)
    return ObservationBundle(
        observations=tuple(observations),
        inclusions=tuple(inclusions),
        revision=bundle.revision + 1,
        known_targets=bundle.known_targets,
        applied_changesets=(*bundle.applied_changesets, changeset),
    )


def _apply_operation(
    observations: list[Observation],
    inclusions: list[InclusionAssertion],
    operation: CorrectionOp,
) -> tuple[list[Observation], list[InclusionAssertion]]:
    if operation.kind == "confirm_supersession":
        return _replace_observation(observations, operation.observation_id, "confirmed"), inclusions
    if operation.kind == "reject_observation":
        return _replace_observation(observations, operation.observation_id, "rejected"), inclusions
    if operation.kind == "confirm_inclusion":
        return observations, _confirm_inclusion(inclusions, operation)
    if operation.kind == "reclassify_measure":
        return _reclassify(observations, operation), inclusions
    raise ValueError(f"Unsupported correction kind: {operation.kind}")


def _replace_observation(
    observations: list[Observation],
    observation_id: str,
    confirmation_state: ConfirmationState,
) -> list[Observation]:
    replaced: list[Observation] = []
    found = False
    for item in observations:
        if item.observation_id != observation_id:
            replaced.append(item)
            continue
        found = True
        replaced.append(
            replace(
                item,
                lifecycle=replace(item.lifecycle, confirmation_state=confirmation_state),
            )
        )
    if not found:
        raise ValueError(f"Unknown observation_id: {observation_id}")
    return replaced


def _confirm_inclusion(
    inclusions: list[InclusionAssertion],
    operation: CorrectionOp,
) -> list[InclusionAssertion]:
    assertion_id = operation.assertion_id
    if assertion_id is None:
        raise ValueError("confirm_inclusion requires assertion_id.")
    replaced: list[InclusionAssertion] = []
    found = False
    for item in inclusions:
        if item.assertion_id != assertion_id:
            replaced.append(item)
            continue
        found = True
        replaced.append(replace(item, review_state="confirmed"))
    if not found:
        raise ValueError(f"Unknown assertion_id: {assertion_id}")
    return replaced


def _reclassify(
    observations: list[Observation],
    operation: CorrectionOp,
) -> list[Observation]:
    replacement = operation.replacement
    if replacement is None:
        raise ValueError("reclassify_measure requires a replacement observation.")
    if replacement.observation_id == operation.observation_id:
        raise ValueError("Meaning correction must add a new observation id.")
    if replacement.lifecycle.supersedes_id != operation.observation_id:
        raise ValueError("Replacement must explicitly supersede the original observation.")
    if replacement.lifecycle.confirmation_state != "confirmed":
        raise ValueError("Reclassified replacement must be a confirmed supersession.")
    originals = {item.observation_id for item in observations}
    if operation.observation_id not in originals:
        raise ValueError(f"Unknown observation_id: {operation.observation_id}")
    if replacement.observation_id in originals:
        raise ValueError("Replacement observation_id already exists.")
    return [*observations, replacement]
