"""YAML field schema-check helpers for report_filters parsing.

Owns structured validation errors and the leaf string/date/mapping/list checks
used by excluded-entry parsers. Entry parsers and the report_filters
orchestrator stay in :mod:`finjuice.pipeline.tagging.rules_yaml_filters`,
which re-exports these helpers so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, NoReturn

from finjuice.pipeline.tagging.models import FiltersValidationError


def _raise_filters_validation_error(
    rules_path: Path,
    key_path: str,
    message: str,
    *,
    accepted_values: set[str] | None = None,
) -> NoReturn:
    """Raise a structured FiltersValidationError for one schema failure."""
    raise FiltersValidationError(
        rules_path,
        key_path,
        message,
        accepted_values=sorted(accepted_values) if accepted_values else None,
    )


def _validate_filter_required_string(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
) -> str:
    """Validate a required non-empty string in report_filters."""
    if not isinstance(value, str):
        _raise_filters_validation_error(rules_path, key_path, "must be a string")
    stripped = value.strip()
    if not stripped:
        _raise_filters_validation_error(rules_path, key_path, "cannot be empty")
    return stripped


def _normalize_filter_date(value: Any, *, rules_path: Path, key_path: str) -> str:
    """Normalize a YAML date/string value into ISO YYYY-MM-DD form."""
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        _raise_filters_validation_error(rules_path, key_path, "must be an ISO date string")
    stripped = value.strip()
    try:
        return date.fromisoformat(stripped).isoformat()
    except ValueError as exc:
        _raise_filters_validation_error(
            rules_path,
            key_path,
            "must be an ISO date string in YYYY-MM-DD format",
        )
        raise exc  # pragma: no cover


def _validate_filter_mapping(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
    allowed_keys: set[str],
) -> dict[str, Any]:
    """Validate a report_filters entry mapping and reject unknown keys."""
    if not isinstance(value, dict):
        _raise_filters_validation_error(rules_path, key_path, "must be a mapping")

    unknown_keys = set(value) - allowed_keys
    if unknown_keys:
        unknown_key = sorted(unknown_keys)[0]
        _raise_filters_validation_error(
            rules_path,
            f"{key_path}.{unknown_key}",
            "unknown field",
            accepted_values=allowed_keys,
        )

    return value


def _validate_filter_list(
    value: Any,
    *,
    rules_path: Path,
    key_path: str,
) -> list[Any]:
    """Normalize an optional report_filters list field."""
    if value is None:
        return []
    if not isinstance(value, list):
        _raise_filters_validation_error(rules_path, key_path, "must be a list")
    return value
