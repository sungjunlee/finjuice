"""Helpers for persisted manual tag edits and category overrides."""

from __future__ import annotations

import json
from typing import Any

MANUAL_CATEGORY_PREFIX = "__finjuice_category_override__:"


def normalize_tag_list(value: Any) -> list[str]:
    """Normalize supported tag collection inputs to a unique list of strings."""
    if value is None:
        return []

    items: list[Any]
    if isinstance(value, list):
        items = value
    elif isinstance(value, (tuple, set)):
        items = list(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            items = [stripped]
        else:
            if decoded is None:
                return []
            if isinstance(decoded, list):
                items = decoded
            else:
                items = [decoded]
    else:
        items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item is None:
            continue
        tag = str(item).strip()
        if not tag or tag in seen:
            continue
        normalized.append(tag)
        seen.add(tag)
    return normalized


def split_manual_tags(tags_manual: Any) -> tuple[list[str], str | None]:
    """Split visible manual tags from the persisted category override marker."""
    visible_tags: list[str] = []
    category_override: str | None = None

    for tag in normalize_tag_list(tags_manual):
        if tag.startswith(MANUAL_CATEGORY_PREFIX):
            override = tag.removeprefix(MANUAL_CATEGORY_PREFIX).strip()
            if override:
                category_override = override
            continue
        visible_tags.append(tag)

    return visible_tags, category_override


def build_manual_tags(tags_manual: Any, category_override: str | None = None) -> list[str]:
    """Build the persisted tags_manual payload, including category override state."""
    visible_tags = normalize_tag_list(tags_manual)
    persisted = list(visible_tags)
    if category_override:
        persisted.append(f"{MANUAL_CATEGORY_PREFIX}{category_override.strip()}")
    return persisted


def merge_final_tags(*tag_groups: Any) -> list[str]:
    """Merge tag collections into a stable unique final tag list."""
    merged: list[str] = []
    seen: set[str] = set()

    for tag_group in tag_groups:
        for tag in normalize_tag_list(tag_group):
            if tag.startswith(MANUAL_CATEGORY_PREFIX) or tag in seen:
                continue
            merged.append(tag)
            seen.add(tag)

    return merged


def resolve_category_final(
    category_rule: Any,
    minor_raw: Any,
    major_raw: Any,
    *,
    tags_manual: Any = None,
) -> str:
    """Resolve category_final, preferring persisted manual override when present."""
    _, category_override = split_manual_tags(tags_manual)
    if category_override:
        return category_override

    for candidate in (category_rule, minor_raw, major_raw):
        if candidate is None:
            continue
        normalized = str(candidate).strip()
        if normalized:
            return normalized

    return "미분류"


def strip_sentinels(tags: Any) -> list[str]:
    """Remove internal ``__finjuice_*`` sentinel values from a tag list."""
    return [t for t in normalize_tag_list(tags) if not t.startswith("__finjuice_")]


def strip_sentinels_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *row* with sentinels stripped from tag fields."""
    cleaned = dict(row)
    for field in ("tags_manual", "tags_final"):
        if field in cleaned:
            cleaned[field] = strip_sentinels(cleaned[field])
    return cleaned


def present_manual_state(transaction: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON/text-safe transaction view without the internal marker."""
    rendered = dict(transaction)
    rendered["notes_manual"] = str(rendered.get("notes_manual") or "")
    manual_tags, category_override = split_manual_tags(rendered.get("tags_manual"))
    rendered["tags_rule"] = normalize_tag_list(rendered.get("tags_rule"))
    rendered["tags_ai"] = normalize_tag_list(rendered.get("tags_ai"))
    rendered["tags_manual"] = manual_tags
    rendered["tags_final"] = merge_final_tags(
        rendered.get("tags_rule"),
        rendered.get("tags_ai"),
        manual_tags,
    )
    rendered["category_manual"] = category_override
    rendered["category_final"] = resolve_category_final(
        rendered.get("category_rule"),
        rendered.get("minor_raw"),
        rendered.get("major_raw"),
        tags_manual=build_manual_tags(manual_tags, category_override),
    )
    return rendered
