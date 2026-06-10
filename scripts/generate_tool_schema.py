#!/usr/bin/env python3
"""Generate a machine-readable tool schema for the finjuice CLI."""

from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import click
import typer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from finjuice import get_version  # noqa: E402
from finjuice.pipeline.cli.introspection import (  # noqa: E402
    build_parameters_schema,
    has_json_flag,
    iter_executable_commands,
)
from finjuice.pipeline.cli.main import app  # noqa: E402

JSON_SCHEMA_URL = "https://json-schema.org/draft-07/schema#"
TOOLS_OUTPUT_PATH = PROJECT_ROOT / "templates" / "tools.json"
JSON_SCHEMA_DOCS_PATH = PROJECT_ROOT / "docs" / "reference" / "json-schemas.md"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"

HEADING_PATTERN = re.compile(r"^### `finjuice (?P<command>[^`]+)`\s*$", re.MULTILINE)
JSON_BLOCK_PATTERN = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def normalize_doc_command(raw_command: str) -> str:
    """Normalize markdown command headings to dotted tool names."""
    tokens = [token for token in raw_command.split() if not token.startswith("--")]
    return ".".join(tokens)


def normalize_schema_artifact_name(filename: str) -> str:
    """Normalize a schema artifact filename to a dotted tool name."""
    schema_name = filename.removesuffix(".schema.json")
    return schema_name.replace("_", ".")


def extract_section_description(section: str) -> str:
    """Extract the first descriptive paragraph before the first code block."""
    text_before_code = section.split("```", 1)[0]
    lines = [line.strip() for line in text_before_code.splitlines()]
    paragraph_lines: list[str] = []

    for line in lines:
        if not line:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)

    return " ".join(paragraph_lines)


def extract_first_paragraph(text: str) -> str:
    """Collapse the first paragraph of a multi-line help string."""
    lines = [line.strip() for line in text.splitlines()]
    paragraph_lines: list[str] = []

    for line in lines:
        if not line:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)

    return " ".join(paragraph_lines)


def infer_array_commands(doc_text: str) -> set[str]:
    """Extract commands documented as array outputs in the global notes."""
    match = re.search(r"List-type outputs \((?P<body>[^)]+)\)", doc_text)
    if match is None:
        return set()

    names = set()
    for raw_name in re.findall(r"`([^`]+)`", match.group("body")):
        tokens = raw_name.split()
        if len(tokens) == 1:
            names.add(tokens[0])
    return names


def merge_object_keys(samples: list[dict[str, Any]]) -> list[str]:
    """Merge top-level keys while preserving their first-seen order."""
    seen: set[str] = set()
    merged: list[str] = []

    for sample in samples:
        for key in sample:
            if key in seen:
                continue
            seen.add(key)
            merged.append(key)

    if merged and "_meta" not in seen:
        merged.insert(0, "_meta")

    return merged


def merge_array_item_keys(samples: list[list[Any]]) -> list[str]:
    """Merge top-level item keys for array samples containing objects."""
    seen: set[str] = set()
    merged: list[str] = []

    for sample in samples:
        for item in sample:
            if not isinstance(item, dict):
                continue
            for key in item:
                if key in seen:
                    continue
                seen.add(key)
                merged.append(key)

    return merged


def build_lightweight_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build the compact output_schema descriptor used in templates/tools.json."""
    schema_type = schema.get("type")
    if not isinstance(schema_type, str):
        schema_type = "object"

    description = schema.get("description") or schema.get("title") or ""
    if not isinstance(description, str):
        description = ""

    output_schema: dict[str, Any] = {
        "type": schema_type,
        "description": description,
    }

    if schema_type == "object":
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and properties:
            output_schema["top_level_keys"] = list(properties)
    elif schema_type == "array":
        items = schema.get("items", {})
        if isinstance(items, dict):
            properties = items.get("properties", {})
            if isinstance(properties, dict) and properties:
                output_schema["item_keys"] = list(properties)

    return output_schema


def load_output_schema_artifacts(schema_dir: Path = SCHEMAS_DIR) -> dict[str, dict[str, Any]]:
    """Load compact output schema metadata from generated JSON Schema artifacts."""
    output_schemas: dict[str, dict[str, Any]] = {}

    for schema_path in sorted(schema_dir.glob("*.schema.json")):
        if schema_path.name.startswith("_"):
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(schema, dict):
            continue

        command_name = normalize_schema_artifact_name(schema_path.name)
        output_schemas[command_name] = build_lightweight_output_schema(schema)

    return output_schemas


def load_output_schema_docs(doc_path: Path = JSON_SCHEMA_DOCS_PATH) -> dict[str, dict[str, Any]]:
    """Parse lightweight output schema metadata from the JSON schema reference."""
    artifact_schemas = load_output_schema_artifacts()
    if artifact_schemas:
        return artifact_schemas

    doc_text = doc_path.read_text(encoding="utf-8")
    headings = list(HEADING_PATTERN.finditer(doc_text))
    array_commands = infer_array_commands(doc_text)
    output_schemas: dict[str, dict[str, Any]] = {}

    for index, match in enumerate(headings):
        command_name = normalize_doc_command(match.group("command"))
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(doc_text)
        section = doc_text[start:end].strip()

        description = extract_section_description(section)
        parsed_json_blocks: list[Any] = []
        for block in JSON_BLOCK_PATTERN.findall(section):
            try:
                parsed_json_blocks.append(json.loads(block))
            except json.JSONDecodeError:
                continue

        object_samples = [sample for sample in parsed_json_blocks if isinstance(sample, dict)]
        array_samples = [sample for sample in parsed_json_blocks if isinstance(sample, list)]

        if object_samples:
            schema: dict[str, Any] = {
                "type": "object",
                "description": description,
            }
            top_level_keys = merge_object_keys(object_samples)
            if top_level_keys:
                schema["top_level_keys"] = top_level_keys
        elif array_samples or command_name in array_commands or "JSON array" in section:
            schema = {
                "type": "array",
                "description": description,
            }
            item_keys = merge_array_item_keys(array_samples)
            if item_keys:
                schema["item_keys"] = item_keys
        else:
            schema = {
                "type": "object",
                "description": description,
            }

        output_schemas[command_name] = schema

    return output_schemas


def build_tool_definition(
    name: str,
    command: click.Command,
    output_schema_docs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build a single tool definition entry."""
    description = extract_first_paragraph((command.help or command.short_help or "").strip())

    return {
        "name": name,
        "description": description,
        "parameters": build_parameters_schema(command),
        "output_schema": output_schema_docs.get(name) if has_json_flag(command) else None,
    }


def collect_source_paths(click_app: click.Group) -> list[Path]:
    """Collect source files that materially affect the generated schema."""
    paths = {
        Path(__file__).resolve(),
        JSON_SCHEMA_DOCS_PATH.resolve(),
        (PROJECT_ROOT / "src" / "finjuice" / "pipeline" / "cli" / "main.py").resolve(),
    }

    for _, command in iter_executable_commands(click_app):
        callback = getattr(command, "callback", None)
        if callback is None:
            continue
        source_file = inspect.getsourcefile(callback)
        if source_file is None:
            continue
        paths.add(Path(source_file).resolve())

    return sorted(paths)


def compute_generated_at(click_app: click.Group) -> str:
    """Return a stable ISO 8601 timestamp derived from source file mtimes."""
    source_paths = collect_source_paths(click_app)
    latest_mtime = max(path.stat().st_mtime for path in source_paths)
    timestamp = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).replace(microsecond=0)
    return timestamp.isoformat()


def build_tool_schema_payload() -> dict[str, Any]:
    """Build the complete tool schema payload."""
    click_app = cast(click.Group, typer.main.get_command(app))
    output_schema_docs = load_output_schema_docs()
    tools = [
        build_tool_definition(name, command, output_schema_docs)
        for name, command in iter_executable_commands(click_app)
    ]

    return {
        "$schema": JSON_SCHEMA_URL,
        "name": "finjuice",
        "version": get_version(),
        "generated_at": compute_generated_at(click_app),
        "tools": tools,
    }


def generate_tool_schema(output_path: Path = TOOLS_OUTPUT_PATH) -> dict[str, Any]:
    """Generate and write the tool schema JSON file."""
    payload = build_tool_schema_payload()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    """CLI entry point."""
    payload = generate_tool_schema()
    print(f"✅ Generated templates/tools.json ({len(payload['tools'])} tools)")


if __name__ == "__main__":
    main()
