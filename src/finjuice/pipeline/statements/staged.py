"""Capture only local JSON documents claiming the canonical statement schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.statements.canonical_parse import STATEMENT_SCHEMA_VERSION
from finjuice.pipeline.storage.sqlite.backup_io import BackupPayloadError, read_regular_bytes

MAX_STATEMENT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class StatementCapture:
    """One selected document, retained without reopening the observed source path."""

    filename: str
    content: bytes
    digest_hex: str


def capture_statement(path: Path) -> StatementCapture | None:
    """Select by schema claim; unrelated or undecodable JSON is not an ingest input."""
    try:
        content = read_regular_bytes(path, max_bytes=MAX_STATEMENT_BYTES)
        envelope = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, BackupPayloadError):
        return None
    if not isinstance(envelope, dict) or envelope.get("schema_version") != STATEMENT_SCHEMA_VERSION:
        return None
    return StatementCapture(path.name, content, hashlib.sha256(content).hexdigest())
