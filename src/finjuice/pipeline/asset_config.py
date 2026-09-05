"""Typed assets.yaml load/parse contracts and validators.

YAML path-location helpers live in
:mod:`finjuice.pipeline.asset_config_helpers` and are re-exported here so
existing callers can keep importing from this module.

Payload validators live in :mod:`finjuice.pipeline.asset_config_validate`
and are re-exported here for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from finjuice.pipeline.asset_config_helpers import (
    _build_path_locations,
)
from finjuice.pipeline.asset_config_helpers import (
    _lookup_location as _lookup_location,
)
from finjuice.pipeline.asset_config_helpers import (
    _parent_path as _parent_path,
)
from finjuice.pipeline.asset_config_helpers import (
    _walk_node as _walk_node,
)

ASSET_CONFIG_VERSION = 1
ASSET_CATEGORIES = ("real_estate", "deposit", "financial", "cash", "other")

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


from finjuice.pipeline.asset_config_validate import (  # noqa: E402, I001
    _ASSET_TOP_LEVEL_KEYS as _ASSET_TOP_LEVEL_KEYS,
    _LIABILITY_KEYS as _LIABILITY_KEYS,
    _MANUAL_ASSET_KEYS as _MANUAL_ASSET_KEYS,
    _add_issue as _add_issue,
    _optional_number as _optional_number,
    _optional_string as _optional_string,
    _require_number as _require_number,
    _require_string as _require_string,
    _validate_assets_payload,
    _validate_liabilities as _validate_liabilities,
    _validate_manual_assets as _validate_manual_assets,
)


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
