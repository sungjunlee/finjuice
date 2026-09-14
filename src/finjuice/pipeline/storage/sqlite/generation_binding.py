"""Generation identity shared by active and explicitly admitted inactive writers."""

from __future__ import annotations

from dataclasses import dataclass

from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths


@dataclass(frozen=True)
class GenerationBinding:
    """A validated generation identity, not an activation or admission credential.

    The caller must independently admit and lease the generation before invoking
    the shared mutation engine. This value never grants authority by itself.
    """

    paths: GenerationPaths
    dataset_generation: str
    sqlite_schema_version: int
    baseline_revision: int

    def __post_init__(self) -> None:
        validate_entity_id(self.dataset_generation)
        if type(self.sqlite_schema_version) is not int or self.sqlite_schema_version < 1:
            raise ValueError("Generation schema version must be a positive integer.")
        if type(self.baseline_revision) is not int or self.baseline_revision < 0:
            raise ValueError("Generation baseline revision must be a non-negative integer.")


def as_generation_binding(authority: RepositoryAuthority | GenerationBinding) -> GenerationBinding:
    """Project identity checks while retaining the original active handler context."""
    if isinstance(authority, GenerationBinding):
        return authority
    activation = authority.activation
    return GenerationBinding(
        authority.paths,
        activation.dataset_generation,
        activation.sqlite_schema_version,
        activation.dataset_revision,
    )
