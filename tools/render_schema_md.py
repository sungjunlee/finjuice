"""Render human-readable JSON Schema reference from generated artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"


def _load_schema(path: Path) -> dict[str, Any]:
    """Load one generated JSON Schema artifact."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _type_label(schema: dict[str, Any]) -> str:
    """Return a compact type label for markdown tables."""
    if "$ref" in schema:
        return f"`$ref` {schema['$ref']}"
    if "enum" in schema:
        values = ", ".join(f"`{value}`" for value in schema["enum"])
        return f"enum({values})"
    if "anyOf" in schema:
        return " or ".join(_type_label(item) for item in schema["anyOf"])

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " \\| ".join(f"`{item}`" for item in schema_type)
    if isinstance(schema_type, str):
        if schema_type == "array":
            item_schema = schema.get("items", {})
            return f"`array`[{_type_label(item_schema)}]"
        return f"`{schema_type}`"
    return "`any`"


def _required_fields(schema: dict[str, Any]) -> str:
    """Render the required top-level field list."""
    required = [field for field in schema.get("required", []) if field != "_meta"]
    if not required:
        return "-"
    return ", ".join(f"`{field}`" for field in required)


def _render_properties(schema: dict[str, Any]) -> list[str]:
    """Render top-level schema properties as a markdown table."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or not properties:
        return []

    required = set(schema.get("required", []))
    lines = [
        "| Field | Type | Required |",
        "|-------|------|----------|",
    ]
    for name, property_schema in sorted(properties.items()):
        if not isinstance(property_schema, dict):
            property_schema = {}
        required_label = "yes" if name in required else "no"
        lines.append(f"| `{name}` | {_type_label(property_schema)} | {required_label} |")
    return lines


def _schema_sort_key(path: Path) -> tuple[int, str]:
    """Keep shared envelopes first, then command schemas alphabetically."""
    if path.name == "_meta.schema.json":
        return (0, path.name)
    if path.name == "_error.schema.json":
        return (1, path.name)
    return (2, path.name)


def render_markdown() -> str:
    """Build markdown documentation from schemas/*.schema.json."""
    schema_paths = sorted(SCHEMAS_DIR.glob("*.schema.json"), key=_schema_sort_key)
    lines = [
        "# JSON Output Schema Reference",
        "",
        "> Generated from `schemas/*.schema.json`. Run `just docs-output-schemas` to update.",
        "",
        "finjuice command JSON outputs use Draft 2020-12 schemas. Command schemas include",
        "`_meta` by reference and keep additive fields open unless a command contract requires",
        "a stricter nested shape.",
        "",
        "`review --json`, `rules suggest --json`, `automation run --json`,",
        "`checkup --json`, and `index --json` support `--privacy raw|redacted|compact`;",
        "`_meta.privacy.profile` identifies the applied profile. The default is",
        "raw-compatible for backward compatibility. `query --json` intentionally does not",
        "expose privacy profiles because",
        "arbitrary SQL projections can rename or compute sensitive row fields outside a stable",
        "redaction contract.",
        "",
        "Schemas for privacy-enabled commands model the shared envelope plus profile-specific",
        "variants: raw/redacted keep the raw object shape with masked values where applicable,",
        "while compact may remove path/sample fields and replace bulky collections with counts.",
        "",
        "**Error envelopes are part of the CLI JSON contract.** When a `--json` invocation",
        "fails, the process emits an object matching `schemas/_error.schema.json` — a `_meta`",
        "block, an `error` object with a stable machine-readable `code` (see the enum in that",
        "schema) and a human `message`, and a process `exit_code`. Agents should branch on",
        "`error.code` rather than parsing `error.message`. The failure-mode matrix lives in",
        "`tests/cli/test_error_envelope_contract_matrix.py` and pins representative",
        "command/code/exit-code combinations against this schema.",
        "",
        "## Artifact Catalog",
        "",
        "| Artifact | Title | Required result fields |",
        "|----------|-------|------------------------|",
    ]

    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in schema_paths:
        schema = _load_schema(path)
        loaded.append((path, schema))
        title = schema.get("title", path.stem)
        lines.append(f"| `schemas/{path.name}` | {title} | {_required_fields(schema)} |")

    for path, schema in loaded:
        title = schema.get("title", path.stem)
        lines.extend(["", f"## `schemas/{path.name}`", "", str(title), ""])
        property_lines = _render_properties(schema)
        if property_lines:
            lines.extend(property_lines)
            lines.append("")
        lines.extend(
            [
                "```json",
                json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Print rendered markdown to stdout."""
    print(render_markdown(), end="")


if __name__ == "__main__":
    main()
