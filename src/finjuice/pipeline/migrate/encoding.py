"""Canonical JSON and digest helpers for migration manifests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from finjuice.pipeline.migrate.errors import MigrationError


def canonical_bytes(value: Any) -> bytes:
    """Return canonical JSON bytes for digesting."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def digest_text(digest: str) -> str:
    """Prefix a hex digest with ``sha256:``."""
    if digest.startswith("sha256:"):
        return digest
    return f"sha256:{digest}"


def hex_digest(digest: str) -> str:
    """Return the 64-character hex portion of a SHA-256 digest."""
    value = digest.removeprefix("sha256:")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise MigrationError("Digest must be lowercase SHA-256.")
    return value


def load_json_object(path: Any) -> dict[str, Any]:
    """Load one JSON object from a path-like file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError("Manifest is missing.", code="FILE_NOT_FOUND") from exc
    except OSError as exc:
        raise MigrationError("Manifest could not be read.", code="FILE_ACCESS_ERROR") from exc
    except json.JSONDecodeError as exc:
        raise MigrationError("Manifest is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise MigrationError("Manifest is not an object.")
    return payload
