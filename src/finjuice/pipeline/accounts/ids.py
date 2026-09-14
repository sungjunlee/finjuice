"""Opaque stable IDs for parties, accounts, and resources."""

from __future__ import annotations

import uuid


def new_stable_id() -> str:
    """Return a lowercase hyphenated UUIDv4 that is not derived from a label."""
    return str(uuid.uuid4())
