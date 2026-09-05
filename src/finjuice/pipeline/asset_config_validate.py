"""Payload validators for assets.yaml.

Owns mapping/list checks for the parsed assets.yaml document, including
manual-asset and liability entries. YAML path-location helpers and file
validation stay in :mod:`finjuice.pipeline.asset_config_helpers`.
Dataclasses and the public load API stay in
:mod:`finjuice.pipeline.asset_config`, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.asset_config import (
    ASSET_CATEGORIES,
    ASSET_CONFIG_VERSION,
    AssetsConfig,
    AssetsConfigIssue,
    Liability,
    ManualAsset,
)
from finjuice.pipeline.asset_config_helpers import _lookup_location

_ASSET_TOP_LEVEL_KEYS = {"version", "manual_assets", "liabilities"}
_MANUAL_ASSET_KEYS = {"name", "category", "value"}
_LIABILITY_KEYS = {"name", "principal", "rate", "type"}


def _validate_assets_payload(
    payload: Any,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> AssetsConfig:
    """Validate the parsed assets.yaml payload."""
    if not isinstance(payload, dict):
        _add_issue(issues, locations, "assets.yaml", "top-level document must be a mapping")
        return AssetsConfig()

    unknown_top_level = sorted(set(payload) - _ASSET_TOP_LEVEL_KEYS)
    for key in unknown_top_level:
        _add_issue(issues, locations, key, "unknown top-level field")

    version = payload.get("version")
    if version != ASSET_CONFIG_VERSION:
        _add_issue(
            issues,
            locations,
            "version",
            f"must be {ASSET_CONFIG_VERSION}",
        )

    manual_assets_raw = payload.get("manual_assets", [])
    liabilities_raw = payload.get("liabilities", [])

    manual_assets = _validate_manual_assets(manual_assets_raw, locations, issues)
    liabilities = _validate_liabilities(liabilities_raw, locations, issues)

    if issues:
        return AssetsConfig()

    return AssetsConfig(
        version=ASSET_CONFIG_VERSION,
        manual_assets=manual_assets,
        liabilities=liabilities,
    )


def _validate_manual_assets(
    value: Any,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> list[ManualAsset]:
    """Validate the manual_assets block."""
    if value is None:
        return []
    if not isinstance(value, list):
        _add_issue(issues, locations, "manual_assets", "must be a list")
        return []

    assets: list[ManualAsset] = []
    for index, item in enumerate(value):
        path = f"manual_assets[{index}]"
        if not isinstance(item, dict):
            _add_issue(issues, locations, path, "must be a mapping")
            continue

        unknown_keys = sorted(set(item) - _MANUAL_ASSET_KEYS)
        for key in unknown_keys:
            _add_issue(issues, locations, f"{path}.{key}", "unknown field")

        name = _require_string(item, path, "name", locations, issues)
        category = _require_string(item, path, "category", locations, issues)
        value_raw = _require_number(item, path, "value", locations, issues)

        if category is not None and category not in ASSET_CATEGORIES:
            allowed = ", ".join(ASSET_CATEGORIES)
            _add_issue(
                issues,
                locations,
                f"{path}.category",
                f"must be one of: {allowed}",
            )

        if name is None or category is None or value_raw is None:
            continue

        assets.append(ManualAsset(name=name, category=category, value=value_raw))

    return assets


def _validate_liabilities(
    value: Any,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> list[Liability]:
    """Validate the liabilities block."""
    if value is None:
        return []
    if not isinstance(value, list):
        _add_issue(issues, locations, "liabilities", "must be a list")
        return []

    liabilities: list[Liability] = []
    for index, item in enumerate(value):
        path = f"liabilities[{index}]"
        if not isinstance(item, dict):
            _add_issue(issues, locations, path, "must be a mapping")
            continue

        unknown_keys = sorted(set(item) - _LIABILITY_KEYS)
        for key in unknown_keys:
            _add_issue(issues, locations, f"{path}.{key}", "unknown field")

        name = _require_string(item, path, "name", locations, issues)
        principal = _require_number(item, path, "principal", locations, issues)
        rate = _optional_number(item, path, "rate", locations, issues)
        liability_type = _optional_string(item, path, "type", locations, issues)

        if name is None or principal is None:
            continue

        liabilities.append(
            Liability(
                name=name,
                principal=principal,
                rate=rate,
                type=liability_type,
            )
        )

    return liabilities


def _require_string(
    payload: dict[str, Any],
    parent_path: str,
    field_name: str,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> str | None:
    """Validate a required non-empty string field."""
    path = f"{parent_path}.{field_name}"
    if field_name not in payload:
        _add_issue(issues, locations, path, "is required")
        return None

    value = payload[field_name]
    if not isinstance(value, str) or not value.strip():
        _add_issue(issues, locations, path, "must be a non-empty string")
        return None
    return value.strip()


def _optional_string(
    payload: dict[str, Any],
    parent_path: str,
    field_name: str,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> str | None:
    """Validate an optional string field."""
    if field_name not in payload or payload[field_name] is None:
        return None

    value = payload[field_name]
    if not isinstance(value, str) or not value.strip():
        _add_issue(issues, locations, f"{parent_path}.{field_name}", "must be a non-empty string")
        return None
    return value.strip()


def _require_number(
    payload: dict[str, Any],
    parent_path: str,
    field_name: str,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> float | None:
    """Validate a required numeric field."""
    path = f"{parent_path}.{field_name}"
    if field_name not in payload:
        _add_issue(issues, locations, path, "is required")
        return None

    value = payload[field_name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _add_issue(issues, locations, path, "must be a number")
        return None
    return float(value)


def _optional_number(
    payload: dict[str, Any],
    parent_path: str,
    field_name: str,
    locations: dict[str, tuple[int, int]],
    issues: list[AssetsConfigIssue],
) -> float | None:
    """Validate an optional numeric field."""
    if field_name not in payload or payload[field_name] is None:
        return None

    value = payload[field_name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _add_issue(issues, locations, f"{parent_path}.{field_name}", "must be a number")
        return None
    return float(value)


def _add_issue(
    issues: list[AssetsConfigIssue],
    locations: dict[str, tuple[int, int]],
    path: str,
    message: str,
) -> None:
    """Append a validation issue with the best available YAML location."""
    line, column = _lookup_location(locations, path)
    issues.append(AssetsConfigIssue(path=path, message=message, line=line, column=column))
