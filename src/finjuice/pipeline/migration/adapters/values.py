"""Lossless legacy field decoding without normalization or inferred currency."""

from __future__ import annotations

import json

from finjuice.pipeline.storage.sqlite.errors import ExactValueError
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY, ExactValue, ValueKind

from .model import Emitter


def exact(
    emitter: Emitter,
    row: dict[str, str | None],
    field: str,
    kind: ValueKind = "money",
    *,
    unit: str | None = None,
) -> str | None:
    parsed = parse_exact(emitter, row, field, kind, unit=unit)
    return emit_exact(emitter, field, parsed)


def parse_exact(
    emitter: Emitter,
    row: dict[str, str | None],
    field: str,
    kind: ValueKind = "money",
    *,
    unit: str | None = None,
) -> ExactValue | None:
    """Decode exact evidence before any typed row or value is inserted."""
    value = row.get(field)
    if value is None:
        return None
    if value == "":
        emitter.issue("untyped_exact_blank", field, value)
        return None
    try:
        currency = (row.get("currency") or UNKNOWN_CURRENCY) if kind == "money" else None
        parsed = ExactValue.from_lexical(
            value, value_kind=kind, origin_kind="migration", currency=currency, unit=unit
        )
    except ExactValueError:
        emitter.issue("invalid_exact_value", field, value)
        return None
    return parsed


def emit_exact(emitter: Emitter, field: str, parsed: ExactValue | None) -> str | None:
    """Insert a parsed value after the containing row passes target constraints."""
    if parsed is None:
        return None
    identifier = emitter.identifier("exact_value", field=field)
    emitter.call(
        "add_exact_value", identifier, parsed, provenance_id=emitter.identifier("provenance")
    )
    emitter.records["exact_value"] += 1
    return identifier


def tags(emitter: Emitter, row: dict[str, str | None], field: str) -> list[str] | None:
    value = row.get(field)
    if value is None or value == "":
        emitter.issue("untyped_tag_state", field, value)
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list) or any(not isinstance(tag, str) for tag in parsed):
        emitter.issue("invalid_tag_sequence", field, value)
        return None
    return parsed


def flag(emitter: Emitter, row: dict[str, str | None], field: str) -> bool | None:
    value = row.get(field)
    if value is None:
        return None
    if value in {"1", "true", "True"}:
        return True
    if value in {"0", "false", "False"}:
        return False
    emitter.issue("invalid_optional_flag", field, value)
    return None
