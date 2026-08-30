"""YAML path location helpers for assets.yaml validation.

Owns composed-document walking and path-to-(line, column) lookup. Public
load/validate functions stay in :mod:`finjuice.pipeline.asset_config`, which
re-exports these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


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
