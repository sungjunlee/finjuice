"""Stable and deterministic IDs for SQLite preservation storage."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any, Final

from finjuice.pipeline.storage.sqlite.errors import IdentifierError

MIGRATION_NAMESPACE: Final = uuid.UUID("fd6b8bfd-e7db-5103-8513-66a572addf54")
_DIGEST_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_RECORD_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def new_entity_id() -> str:
    """Return a lowercase, hyphenated UUIDv4 from the platform secure source."""
    return str(uuid.uuid4())


def canonical_locator(locator: Mapping[str, Any]) -> str:
    """Encode a versioned legacy locator without normalizing its string values."""
    if not locator:
        raise IdentifierError("Legacy locator must not be empty.")
    if set(locator) <= {"row_hash"}:
        raise IdentifierError("row_hash alone cannot identify a legacy occurrence.")
    try:
        return json.dumps(
            locator,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise IdentifierError("Legacy locator must contain canonical JSON values.") from exc


def migration_entity_id(
    capture_manifest_digest: str,
    record_kind: str,
    legacy_locator: Mapping[str, Any],
) -> str:
    """Return the contract UUIDv5 for one frozen legacy record occurrence."""
    digest_match = _DIGEST_RE.fullmatch(capture_manifest_digest)
    if digest_match is None:
        raise IdentifierError("Capture manifest digest must be lowercase SHA-256.")
    if _RECORD_KIND_RE.fullmatch(record_kind) is None:
        raise IdentifierError("Migration record kind must be a fixed lowercase token.")
    locator_json = canonical_locator(legacy_locator)
    name = f"{digest_match.group(1)}/{record_kind}/{locator_json}"
    return str(uuid.uuid5(MIGRATION_NAMESPACE, name))


def validate_entity_id(value: str) -> str:
    """Validate and return one canonical UUID string."""
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise IdentifierError("Entity ID must be a canonical UUID string.") from exc
    if str(parsed) != value:
        raise IdentifierError("Entity ID must be lowercase and hyphenated.")
    return value
