"""Config document types and lexical YAML helpers for repository mutations.

Owns YAML scalar-preserving parse, ConfigDocument construction, and the
publish helper that turns exact config bytes into a revision mutation.
Public names stay importable from
:mod:`finjuice.pipeline.storage.mutation_facade`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import yaml

from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.mutations import ConfigRevisionMutation
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.records import (
    ConfigRevisionRecord,
    SourceOccurrenceRecord,
)

JSONValue = Any
ConfigKind = Literal["rules", "goals", "assets", "scenarios", "schema", "other"]
ParsedStatus = Literal["parsed", "invalid", "opaque"]

_YAML_SCALAR_TAGS = (
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:binary",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:str",
)


def _construct_lexical_scalar(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> str:
    """Construct a permitted scalar as its source text."""
    return loader.construct_scalar(node)


class _LexicalSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that leaves implicit scalar values as source text."""

    yaml_implicit_resolvers = yaml.BaseLoader.yaml_implicit_resolvers.copy()


for _scalar_tag in _YAML_SCALAR_TAGS:
    _LexicalSafeLoader.add_constructor(_scalar_tag, _construct_lexical_scalar)


def _load_lexical_yaml(content: bytes) -> JSONValue:
    """Parse YAML without executing application-specific object constructors."""
    loader = _LexicalSafeLoader(content)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


@dataclass(frozen=True)
class ConfigDocument:
    """Exact config bytes plus their deterministic parser interpretation."""

    config_kind: ConfigKind
    content: bytes
    parsed_status: ParsedStatus
    canonical_payload: Mapping[str, JSONValue] | list[JSONValue] | None
    parser_version: str | None

    @classmethod
    def from_validated_yaml(
        cls,
        config_kind: ConfigKind,
        content: bytes,
        *,
        parser_version: str,
    ) -> ConfigDocument:
        """Build parsed config metadata without losing numeric lexical text."""
        try:
            canonical_payload = _load_lexical_yaml(content)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("Validated YAML bytes could not be parsed canonically.") from exc
        if canonical_payload is not None and not isinstance(canonical_payload, (Mapping, list)):
            raise ValueError("A canonical config document must be a mapping or list.")
        return cls(
            config_kind=config_kind,
            content=content,
            parsed_status="parsed",
            canonical_payload=canonical_payload,
            parser_version=parser_version,
        )


@dataclass(frozen=True)
class ConfigTransformResult:
    """One semantic config transformation and its stable command result."""

    document: ConfigDocument
    result: Mapping[str, JSONValue]


@dataclass(frozen=True)
class ConfigMutation:
    """Stable semantic config intent plus its lock-scoped transformer."""

    config_kind: ConfigKind
    semantic_payload: Mapping[str, JSONValue]
    transformer: Callable[[bytes | None], ConfigTransformResult]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _publish_config_mutation(
    authority: RepositoryAuthority,
    document: ConfigDocument,
) -> ConfigRevisionMutation:
    artifact = SourceObjectStore(authority.paths).publish(io.BytesIO(document.content))
    created_at = _now()
    occurrence_id = new_entity_id()
    return ConfigRevisionMutation(
        revision=ConfigRevisionRecord(
            revision_id=new_entity_id(),
            config_kind=document.config_kind,
            artifact_id=artifact.artifact_id,
            occurrence_id=occurrence_id,
            parsed_status=document.parsed_status,
            parser_version=document.parser_version,
            canonical_payload=document.canonical_payload,
        ),
        occurrence=SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind="config_revision",
            original_filename=f"{document.config_kind}.yaml",
            imported_at=created_at,
            parser_version=document.parser_version,
            source_schema_version=None,
            legacy_path=None,
        ),
        artifact=artifact,
        updated_at=created_at,
    )
