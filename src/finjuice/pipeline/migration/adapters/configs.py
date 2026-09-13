"""Preserve configuration source bytes and conservatively parsed revisions."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.migration.policy import PORTFOLIO_CONFIG_POLICY
from finjuice.pipeline.storage.sqlite.records import ConfigRevisionRecord
from finjuice.pipeline.yaml_exact import ExactFloatLexeme, configure_exact_floats

from .model import PARSER, Emitter

KINDS = {"rules", "goals", "assets", "scenarios", "schema"}


def config_kind(path: str) -> str | None:
    name = PurePosixPath(path)
    if name.stem in KINDS and name.suffix.lower() in {".yaml", ".yml", ".json"}:
        return name.stem
    return None


def config(emitter: Emitter, data: bytes, artifact: str, kind: Any) -> bool:
    parsed: Any = None
    status: Any = "parsed"
    try:
        text = data.decode("utf-8-sig")
        if emitter.context.relative_path.lower().endswith(".json"):
            parsed = json.loads(
                text,
                parse_float=ExactFloatLexeme,
                parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
        else:
            parsed = configure_exact_floats(YAML(typ="safe")).load(text)
        # Unsupported YAML scalar types and cyclic aliases stay exact byte evidence.
        if _has_decimal_lexeme(parsed):
            emitter.issue("config_decimal_lexical_representation")
        json.dumps(parsed, ensure_ascii=False, allow_nan=False)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("Unsupported configuration structure")
    except (UnicodeError, ValueError, TypeError, YAMLError, RecursionError):
        status = "invalid"
        parsed = None
        emitter.issue("unsupported_config_parse")
    identifier = emitter.identifier("config_revision")
    emitter.entity(
        "config_revision",
        ConfigRevisionRecord(
            identifier, kind, artifact, emitter.occurrence, status, PARSER, parsed
        ),
    )
    if kind in {"rules", "goals"} or (
        emitter.context.migration_policy == PORTFOLIO_CONFIG_POLICY
        and kind in {"assets", "scenarios"}
    ):
        timestamp = emitter.context.config_head_timestamp
        if timestamp is not None:
            emitter.call("set_config_head", kind, identifier, updated_at=timestamp)
            emitter.records["config_head"] += 1
            if status == "invalid":
                emitter.issue("canonical_config_head_invalid")
        else:
            emitter.issue("config_head_requires_explicit_selection")
    return bool(status == "parsed")


def _reject_constant(value: str) -> Any:
    raise ValueError("Non-finite JSON value")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key")
        result[key] = value
    return result


def _has_decimal_lexeme(value: Any) -> bool:
    if isinstance(value, ExactFloatLexeme):
        return True
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Non-string configuration key")
        return any(_has_decimal_lexeme(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_decimal_lexeme(item) for item in value)
    return False
