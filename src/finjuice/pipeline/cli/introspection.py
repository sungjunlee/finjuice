"""Helpers for describing the finjuice Typer/Click command surface.

This module is the shared source of truth for CLI command walking and parameter
serialization.  `scripts/generate_tool_schema.py` uses the JSON Schema helpers
for tool descriptors, and `finjuice manifest` uses the same command walker and
parameter metadata to emit a runtime self-description.

JSON Schema parameter helpers live in
:mod:`finjuice.pipeline.cli.introspection_schema` and are re-exported here.
"""

from __future__ import annotations

from typing import Any

import click

from finjuice.pipeline.cli.introspection_schema import (  # noqa: F401
    ENUM_HELP_PATTERNS,
    base_type_schema,
    build_parameter_schema,
    build_parameters_schema,
    has_json_flag,
    infer_enum_from_help,
    make_nullable,
    option_property_name,
    serialize_default,
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
