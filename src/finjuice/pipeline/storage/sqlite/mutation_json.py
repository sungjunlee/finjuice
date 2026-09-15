"""Canonical JSON encoding helpers for the authoritative mutation boundary.

Owns request/result JSON serialization, receipt envelope parsing, JSON tree
validation, and digest hashing. Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.mutations`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, TypeAlias

from finjuice.pipeline.storage.sqlite.errors import (
    MutationValidationError,
    RepositoryIntegrityError,
)

JSONValue: TypeAlias = Any


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is forbidden: {value}")


def _canonical_request_json(value: JSONValue) -> str:
    _validate_json_tree(value, allow_float=False)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError("Authoritative values must be canonical JSON.") from exc


def _canonical_result_json(value: JSONValue) -> str:
    _validate_json_tree(value, allow_float=True)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MutationValidationError("Mutation result must be finite JSON.") from exc


def _parse_receipt_envelope(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("Stored mutation receipt is invalid JSON.") from exc
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"result", "retained_artifacts"}
        or not isinstance(parsed["result"], dict)
        or not isinstance(parsed["retained_artifacts"], list)
        or any(not isinstance(item, str) or not item for item in parsed["retained_artifacts"])
    ):
        raise RepositoryIntegrityError("Stored mutation receipt envelope is invalid.")
    return parsed


def _validate_json_tree(value: JSONValue, *, allow_float: bool) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not allow_float or not math.isfinite(value):
            raise MutationValidationError(
                "Floating-point request/state values are not authoritative."
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise MutationValidationError("JSON object keys must be strings.")
            _validate_json_tree(item, allow_float=allow_float)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_tree(item, allow_float=allow_float)
        return
    raise MutationValidationError("Value is outside the supported JSON contract.")


def _digest(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
