"""Deterministic digests and idempotency keys for agent intake."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from finjuice.pipeline.agent.models import IntakeInput, InterpretationDraft

INTAKE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://github.com/sungjunlee/finjuice/agent/intake/v1",
)


def source_digest(payload: IntakeInput) -> str:
    """Return the SHA-256 digest of original source kind, image, text, and XLSX."""
    hasher = hashlib.sha256()
    hasher.update(payload.source_kind.encode("utf-8"))
    hasher.update(b"\x1f")
    hasher.update(payload.image_bytes)
    hasher.update(b"\x1f")
    hasher.update(payload.description.encode("utf-8"))
    hasher.update(b"\x1f")
    hasher.update(payload.xlsx_bytes)
    return f"sha256:{hasher.hexdigest()}"


def description_digest(description: str) -> str:
    """Return the SHA-256 digest of original description text."""
    return f"sha256:{hashlib.sha256(description.encode('utf-8')).hexdigest()}"


def json_digest(value: Mapping[str, Any]) -> str:
    """Return a canonical JSON SHA-256 digest."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def extraction_digest(extracted: Mapping[str, str]) -> str:
    """Return the digest of extracted fields without interpretation."""
    return json_digest(dict(extracted))


def interpretation_digest(draft: InterpretationDraft) -> str:
    """Return the digest of the interpretation proposal."""
    mapping = draft.account_mapping
    impact = draft.impact
    return json_digest(
        {
            "change_kind": draft.change_kind,
            "account_mapping": {
                "status": mapping.status,
                "candidate_account_id": mapping.candidate_account_id,
                "account_kind": mapping.account_kind,
                "label": mapping.label,
            },
            "impact": {
                "account_ids": list(impact.account_ids),
                "transaction_ids": list(impact.transaction_ids),
                "applies_recurring": impact.applies_recurring,
            },
            "target_id": draft.target_id,
        }
    )


def derived_submit_key(payload: IntakeInput) -> str:
    """Return the derived idempotency key for one submit payload."""
    return json_digest(
        {
            "source_digest": source_digest(payload),
            "extracted": dict(payload.extracted),
            "interpretation": interpretation_digest(payload.interpretation),
        }
    )


def intake_entity_id(name: str) -> str:
    """Return a stable lowercase UUIDv5 for one intake lineage name."""
    return str(uuid5(INTAKE_NAMESPACE, name))
