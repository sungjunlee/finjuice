"""Helpers for describing the finjuice Typer/Click command surface.

This module is the shared source of truth for CLI command walking and parameter
serialization.  `scripts/generate_tool_schema.py` uses the JSON Schema helpers
for tool descriptors, and `finjuice manifest` uses the same command walker and
parameter metadata to emit a runtime self-description.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click

ENUM_HELP_PATTERNS = (
    re.compile(
        r"\b(?:Export|Output)\s+format:\s*([A-Za-z0-9_./-]+(?:\s*,\s*[A-Za-z0-9_./-]+)+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bOne of:\s*([A-Za-z0-9_./-]+(?:\s*,\s*[A-Za-z0-9_./-]+)+)", re.IGNORECASE),
)


def iter_leaf_commands(
    group: click.Group,
    prefix: str = "",
) -> list[tuple[str, click.Command]]:
    """Return all visible executable leaf commands with dotted group prefixes."""
    commands: list[tuple[str, click.Command]] = []

    for name in sorted(group.commands):
        command = group.commands[name]
        full_name = f"{prefix}.{name}" if prefix else name
        if getattr(command, "hidden", False):
            continue
        if isinstance(command, click.Group):
            commands.extend(iter_leaf_commands(command, prefix=full_name))
            continue
        commands.append((full_name, command))

    return commands


def is_executable_command(command: click.Command) -> bool:
    """Return True when a command path is a standalone invocation target."""
    if getattr(command, "callback", None) is None:
        return False
    if isinstance(command, click.Group):
        return bool(getattr(command, "invoke_without_command", False))
    return True


def iter_executable_commands(
    group: click.Group,
    prefix: str = "",
) -> list[tuple[str, click.Command]]:
    """Return all visible standalone invocation targets, including executable groups."""
    commands: list[tuple[str, click.Command]] = []

    for name in sorted(group.commands):
        command = group.commands[name]
        full_name = f"{prefix}.{name}" if prefix else name
        if getattr(command, "hidden", False):
            continue
        if is_executable_command(command):
            commands.append((full_name, command))
        if isinstance(command, click.Group):
            commands.extend(iter_executable_commands(command, prefix=full_name))

    return commands


def rich_help_panel_name(value: Any) -> str | None:
    """Return a concrete Rich help panel name, ignoring Typer placeholders."""
    return value if isinstance(value, str) else None


def iter_leaf_commands_with_panels(
    group: click.Group,
    prefix: str = "",
    inherited_panel: str | None = None,
) -> list[tuple[str, click.Command, str | None]]:
    """Return visible leaf commands with inherited Rich help panel names."""
    commands: list[tuple[str, click.Command, str | None]] = []

    for name in sorted(group.commands):
        command = group.commands[name]
        full_name = f"{prefix}.{name}" if prefix else name
        if getattr(command, "hidden", False):
            continue
        command_panel = rich_help_panel_name(getattr(command, "rich_help_panel", None))
        effective_panel = command_panel or inherited_panel
        if isinstance(command, click.Group):
            commands.extend(
                iter_leaf_commands_with_panels(
                    command,
                    prefix=full_name,
                    inherited_panel=effective_panel,
                )
            )
            continue
        commands.append((full_name, command, effective_panel))

    return commands


def iter_executable_commands_with_panels(
    group: click.Group,
    prefix: str = "",
    inherited_panel: str | None = None,
) -> list[tuple[str, click.Command, str | None]]:
    """Return visible standalone commands with inherited Rich help panel names."""
    commands: list[tuple[str, click.Command, str | None]] = []

    for name in sorted(group.commands):
        command = group.commands[name]
        full_name = f"{prefix}.{name}" if prefix else name
        if getattr(command, "hidden", False):
            continue
        command_panel = rich_help_panel_name(getattr(command, "rich_help_panel", None))
        effective_panel = command_panel or inherited_panel
        if is_executable_command(command):
            commands.append((full_name, command, effective_panel))
        if isinstance(command, click.Group):
            commands.extend(
                iter_executable_commands_with_panels(
                    command,
                    prefix=full_name,
                    inherited_panel=effective_panel,
                )
            )

    return commands


def option_property_name(param: click.Parameter) -> str:
    """Return the agent-facing parameter name for a Click parameter."""
    if isinstance(param, click.Option):
        opts = [str(option) for option in (getattr(param, "opts", []) or [])]
        for option in opts:
            if option.startswith("--") and not option.startswith("--no-"):
                return option[2:].replace("-", "_")
        for option in opts:
            if option.startswith("--"):
                return option[2:].replace("-", "_")
    return (param.name or "").replace("-", "_")


def infer_enum_from_help(help_text: str | None) -> list[str] | None:
    """Extract simple comma-delimited enums from help text when available."""
    if not help_text:
        return None

    for pattern in ENUM_HELP_PATTERNS:
        match = pattern.search(help_text)
        if match is None:
            continue
        values = [value.strip() for value in match.group(1).split(",")]
        if len(values) >= 2 and all(re.fullmatch(r"[A-Za-z0-9_./-]+", value) for value in values):
            return values

    return None


def base_type_schema(param: click.Parameter) -> dict[str, Any]:
    """Map Click/Typer parameter types to JSON Schema types."""
    param_type = param.type

    if isinstance(param_type, click.Choice):
        return {
            "type": "string",
            "enum": list(param_type.choices),
        }
    if isinstance(param_type, click.types.BoolParamType):
        return {"type": "boolean"}
    if isinstance(param_type, click.types.IntParamType):
        return {"type": "integer"}
    if isinstance(param_type, click.types.FloatParamType):
        return {"type": "number"}
    if isinstance(param_type, click.Path) or type(param_type).__name__ == "TyperPath":
        return {
            "type": "string",
            "format": "path",
        }

    schema: dict[str, Any] = {"type": "string"}
    inferred_enum = infer_enum_from_help(getattr(param, "help", None))
    if inferred_enum:
        schema["enum"] = inferred_enum
    return schema


def make_nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow null values for optional parameters with a None default."""
    result = dict(schema)
    current_type = result.get("type")

    if isinstance(current_type, str):
        result["type"] = [current_type, "null"]
    elif isinstance(current_type, list) and "null" not in current_type:
        result["type"] = [*current_type, "null"]

    if "enum" in result and None not in result["enum"]:
        result["enum"] = [*result["enum"], None]

    return result


def serialize_default(value: Any) -> Any:
    """Convert Click defaults into JSON-serializable values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [serialize_default(item) for item in value]
    if isinstance(value, list):
        return [serialize_default(item) for item in value]
    return value


def build_parameter_schema(param: click.Parameter) -> dict[str, Any]:
    """Build a JSON Schema property definition for a single parameter."""
    item_schema = base_type_schema(param)

    if param.nargs != 1 or getattr(param, "multiple", False):
        schema: dict[str, Any] = {
            "type": "array",
            "items": item_schema,
        }
    else:
        schema = dict(item_schema)

    help_text = getattr(param, "help", None)
    if help_text:
        schema["description"] = help_text

    if not param.required and param.default is None:
        schema = make_nullable(schema)

    if not param.required or param.default is not None:
        schema["default"] = serialize_default(param.default)

    return schema


def build_parameters_schema(command: click.Command) -> dict[str, Any]:
    """Build JSON Schema parameters for a Click command."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in command.params:
        if getattr(param, "hidden", False):
            continue
        property_name = option_property_name(param)
        properties[property_name] = build_parameter_schema(param)
        if param.required:
            required.append(property_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    return schema


def has_json_flag(command: click.Command) -> bool:
    """Return True when a command exposes a canonical --json option."""
    for param in command.params:
        if not isinstance(param, click.Option):
            continue
        if "--json" in getattr(param, "opts", []):
            return True
    return False
