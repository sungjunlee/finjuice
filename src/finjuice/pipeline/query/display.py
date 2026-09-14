"""Typed human/JSON display helpers that hide internal classification markers."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.tagging.manual import present_manual_state, strip_sentinels_from_row


def display_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a typed display row without the internal category-override marker.

    The source row is not mutated. Hidden ``__finjuice_*`` sentinels stay in
    the internal frame and compatibility CSV; they are not user tags here.
    """
    return present_manual_state(row)


def display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map :func:`display_row` across a list of internal rows."""
    return [display_row(row) for row in rows]


def strip_display_sentinels(row: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with sentinels stripped from tag fields only."""
    return strip_sentinels_from_row(row)


__all__ = ["display_row", "display_rows", "strip_display_sentinels"]
