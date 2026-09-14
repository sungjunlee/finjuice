"""Hidden-category sentinel split and lossless field helpers."""

from __future__ import annotations

import json
from typing import Any

from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX

_TRUE_VALUES = {"1", "true", "yes"}
_FALSE_VALUES = {"0", "false", "no"}
_TYPE_NORM = {"expense", "income", "transfer", "other"}


def parse_tag_sequence(raw: str | None) -> tuple[list[str], str | None]:
    """Parse a legacy tag cell without deduplicating or stripping sentinels."""
    if raw is None:
        return [], None
    stripped = raw.strip()
    if not stripped:
        return [], None
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return [raw], "invalid_tag_json"
    if decoded is None:
        return [], None
    if not isinstance(decoded, list):
        return [raw], "invalid_tag_json"
    sequence: list[str] = []
    for item in decoded:
        if item is None:
            sequence.append("")
        else:
            sequence.append(str(item))
    return sequence, None


def split_hidden_category(tags: list[str]) -> tuple[list[str], str | None, list[str]]:
    """Split visible tags from hidden category markers.

    The original sequence stays in the legacy payload. Typed ``tags_manual`` is
    the ordered visible subsequence. ``category_manual`` is the last non-empty
    marker. Empty markers are skipped for selection but retained as evidence.
    """
    visible: list[str] = []
    markers: list[str] = []
    selected: str | None = None
    for tag in tags:
        if tag.startswith(MANUAL_CATEGORY_PREFIX):
            markers.append(tag)
            override = tag.removeprefix(MANUAL_CATEGORY_PREFIX).strip()
            if override:
                selected = override
            continue
        visible.append(tag)
    return visible, selected, markers


def canonical_tag_json(tags: list[str]) -> str:
    """Serialize a tag sequence without changing order or membership."""
    return json.dumps(tags, ensure_ascii=False, separators=(",", ":"))


def optional_flag(raw: str | None) -> tuple[bool | None, str | None]:
    """Parse a nullable 1/0 flag without inventing a value."""
    if raw is None:
        return None, None
    if raw == "":
        return None, None
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True, None
    if lowered in _FALSE_VALUES:
        return False, None
    return None, "unparseable_flag"


def normalize_type_norm(raw: str | None) -> tuple[str, str | None]:
    """Return a typed type_norm without reclassifying a valid persisted value."""
    if raw is None or raw == "":
        return "other", "missing_type_norm"
    if raw in _TYPE_NORM:
        return raw, None
    return "other", "unsupported_type_norm"


def money_currency(raw: str | None) -> tuple[str | None, bool, str | None]:
    """Return currency code, unknown flag, and an optional issue kind."""
    if raw is None or raw == "":
        return None, True, None
    if len(raw) == 3 and raw.isalpha() and raw.isupper():
        return raw, False, None
    return None, True, "unsupported_currency"


def field_presence(row: dict[str, str], headers: list[str]) -> dict[str, str]:
    """Describe blank versus present cells for inventoried columns."""
    presence: dict[str, str] = {}
    for header in headers:
        if header not in row:
            presence[header] = "absent"
        elif row[header] == "":
            presence[header] = "blank"
        else:
            presence[header] = "present"
    return presence


def unknown_fields(row: dict[str, str], known: set[str]) -> dict[str, str]:
    """Return extra CSV columns that have no typed destination."""
    return {key: value for key, value in row.items() if key not in known}


def legacy_payload(
    row: dict[str, str],
    headers: list[str],
    known: set[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a lossless payload for one legacy occurrence."""
    extra = extra or {}
    payload: dict[str, Any] = {
        "fields": dict(row),
        "field_presence": field_presence(row, headers),
        "unknown_fields": unknown_fields(row, known),
    }
    if "tags_manual_raw" in extra:
        payload["tags_manual_raw"] = extra["tags_manual_raw"]
    if "markers" in extra:
        payload["category_override_markers"] = extra["markers"]
        payload["representation_code"] = "hidden_category_sentinel_extracted.v1"
    for key, value in extra.items():
        if key not in {"tags_manual_raw", "markers"}:
            payload[key] = value
    return payload
