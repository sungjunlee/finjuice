"""YAML path-location helpers and assets.yaml file validation.

Owns composing path -> (line, column) lookups from a YAML document,
resolving the nearest recorded location for a dotted/indexed path, and
reading/parsing assets.yaml into a structured validation result.
Payload validation lives in :mod:`finjuice.pipeline.asset_config_validate`.
The public load API stays in :mod:`finjuice.pipeline.asset_config`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

if TYPE_CHECKING:
    from finjuice.pipeline.asset_config import AssetsConfigValidationResult


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


def validate_assets_config_file(
    assets_file: Path,
    *,
    allow_missing_file: bool = True,
) -> AssetsConfigValidationResult:
    """Validate assets.yaml and return structured issues."""
    from finjuice.pipeline.asset_config import (
        AssetsConfig,
        AssetsConfigIssue,
        AssetsConfigValidationResult,
    )
    from finjuice.pipeline.asset_config_validate import _validate_assets_payload

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
