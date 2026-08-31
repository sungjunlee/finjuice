"""Warning aggregation helpers for the checkup composer.

Owns de-duplication of per-domain collector warnings. Bundle orchestration
stays in :mod:`finjuice.pipeline.checkup.compose`, which re-exports these
helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations


def _collect_warnings(*messages: str | None) -> list[str]:
    """Return de-duplicated warnings in stable order."""
    warnings: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if not message or message in seen:
            continue
        warnings.append(message)
        seen.add(message)
    return warnings
