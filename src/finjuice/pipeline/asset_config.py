"""Typed assets.yaml load/parse contracts and validators."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

ASSET_CONFIG_VERSION = 1
ASSET_CATEGORIES = ("real_estate", "deposit", "financial", "cash", "other")
_ASSET_TOP_LEVEL_KEYS = {"version", "manual_assets", "liabilities"}
_MANUAL_ASSET_KEYS = {"name", "category", "value"}
_LIABILITY_KEYS = {"name", "principal", "rate", "type"}

__all__ = [
    "ASSET_CATEGORIES",
    "ASSET_CONFIG_VERSION",
    "AssetsConfig",
    "AssetsConfigIssue",
    "AssetsConfigValidationError",
    "AssetsConfigValidationResult",
    "Liability",
    "ManualAsset",
    "load_assets_config",
    "validate_assets_config_file",
]


@dataclass(frozen=True)
class ManualAsset:
    """One manually curated asset entry from assets.yaml."""

    name: str
    category: str
    value: float


@dataclass(frozen=True)
class Liability:
    """One liability entry from assets.yaml."""

    name: str
    principal: float
    rate: float | None = None
    type: str | None = None


@dataclass(frozen=True)
class AssetsConfig:
    """Validated assets.yaml payload."""

    version: int = ASSET_CONFIG_VERSION
    manual_assets: list[ManualAsset] = field(default_factory=list)
    liabilities: list[Liability] = field(default_factory=list)


@dataclass(frozen=True)
class AssetsConfigIssue:
    """One validation issue for assets.yaml."""

    path: str
    message: str
    line: int | None = None
    column: int | None = None

    def format(self) -> str:
        """Return a human-readable error line."""
        location = ""
        if self.line is not None:
            location = f"Line {self.line}"
            if self.column is not None:
                location += f", column {self.column}"
            location += ": "
        return f"{location}{self.path} - {self.message}"


@dataclass(frozen=True)
class AssetsConfigValidationResult:
    """Validation result for assets.yaml."""

    path: Path
    exists: bool
    config: AssetsConfig
    issues: list[AssetsConfigIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when the config is valid or intentionally absent."""
        return not self.issues


class AssetsConfigValidationError(ValueError):
    """Raised when assets.yaml fails schema validation."""

    def __init__(self, path: Path, issues: list[AssetsConfigIssue]) -> None:
        self.path = path
        self.issues = issues
        lines = "\n".join(f"- {issue.format()}" for issue in issues)
        super().__init__(f"Invalid assets.yaml at {path}:\n{lines}")


def load_assets_config(
    assets_file: Path,
    *,
    allow_missing_file: bool = True,
) -> AssetsConfig:
    """Load and validate assets.yaml."""
    result = validate_assets_config_file(assets_file, allow_missing_file=allow_missing_file)
    if not result.is_valid:
        raise AssetsConfigValidationError(assets_file, result.issues)
    return result.config


def validate_assets_config_file(
    assets_file: Path,
    *,
    allow_missing_file: bool = True,
) -> AssetsConfigValidationResult:
    """Validate assets.yaml and return structured issues."""
    if not assets_file.exists():
        return AssetsConfigValidationResult(
            path=assets_file,
            exists=False,
            config=AssetsConfig(),
            issues=(
                []
                if allow_missing_file
                else [AssetsConfigIssue(path="assets.yaml", message="file not found")]
            ),
        )

    raw_text = assets_file.read_text(encoding="utf-8")
    try:
        document = yaml.compose(raw_text)
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        issue = AssetsConfigIssue(
            path="assets.yaml",
            message="invalid YAML syntax",
            line=(mark.line + 1) if mark is not None else None,
            column=(mark.column + 1) if mark is not None else None,
        )
        return AssetsConfigValidationResult(
            path=assets_file,
            exists=True,
            config=AssetsConfig(),
            issues=[issue],
        )

    if payload is None:
        payload = {}

    locations = _build_path_locations(document)
    issues: list[AssetsConfigIssue] = []
    config = _validate_assets_payload(payload, locations, issues)

    return AssetsConfigValidationResult(
        path=assets_file,
        exists=True,
        config=config,
        issues=issues,
    )


def _build_path_locations(node: Node | None) -> dict[str, tuple[int, int]]:
    """Return YAML path -> (line, column) lookups from a composed document."""
    locations: dict[str, tuple[int, int]] = {}
    if node is None:
        return locations
    _walk_node(node, "", locations)
    return locations


def _walk_node(node: Node, path: str, locations: dict[str, tuple[int, int]]) -> None:
    """Populate YAML node locations recursively."""
    locations[path or "$"] = (node.start_mark.line + 1, node.start_mark.column + 1)

    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            key = str(key_node.value)
            child_path = f"{path}.{key}" if path else key
            locations[child_path] = (key_node.start_mark.line + 1, key_node.start_mark.column + 1)
            _walk_node(value_node, child_path, locations)
        return

    if isinstance(node, SequenceNode):
        for index, item_node in enumerate(node.value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            locations[child_path] = (item_node.start_mark.line + 1, item_node.start_mark.column + 1)
            _walk_node(item_node, child_path, locations)


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


def _lookup_location(
    locations: dict[str, tuple[int, int]],
    path: str,
) -> tuple[int | None, int | None]:
    """Find the nearest recorded YAML location for a path."""
    candidate = path
    while candidate:
        if candidate in locations:
            return locations[candidate]
        candidate = _parent_path(candidate)

    return locations.get("$", (None, None))


def _parent_path(path: str) -> str:
    """Return the parent path for a dotted/indexed YAML path."""
    if "." in path:
        return path.rsplit(".", 1)[0]
    if path.endswith("]") and "[" in path:
        return path[: path.rfind("[")]
    return ""
