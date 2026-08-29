"""Per-command spec helpers for ``finjuice manifest``.

Owns command classification tables, Click parameter serialization, and the
per-command spec contract. Manifest envelope assembly, human rendering, and
the Typer command stay in :mod:`finjuice.pipeline.cli.commands.manifest`.
"""

from __future__ import annotations

from typing import Any

import click

from finjuice.pipeline.cli.introspection import (
    base_type_schema,
    has_json_flag,
    option_property_name,
    serialize_default,
)

ERROR_SCHEMA_REF = "schemas/_error.schema.json"

MUTATING_COMMANDS = {
    "all",
    "audit clear",
    "budget edit",
    "doctor",
    "export",
    "import",
    "ingest",
    "init",
    "journal new",
    "journal resume",
    "migrate",
    "refresh",
    "rules add",
    "rules export",
    "rules gaps",
    "rules remove",
    "rules suggest",
    "tag",
    "template run",
    "transfer",
    "update-agents",
    "workspace create",
    "workspace remove",
}

CONFIRMATION_REQUIRED_COMMANDS = MUTATING_COMMANDS | {
    "workspace open",
}

RUNTIME_METADATA_COMMANDS = {
    "doctor",
    "history",
    "manifest",
    "open",
    "update-agents",
    "workspace create",
    "workspace list",
    "workspace open",
    "workspace remove",
    "workspace verify",
}

ARTIFACT_COMMANDS = {
    "export",
    "open",
}

COMMAND_EXAMPLES = {
    "manifest": ["finjuice manifest --json", "finjuice manifest --commands-only --json"],
    "query": ['finjuice query --json "SELECT * FROM transactions LIMIT 5"'],
    "status": ["finjuice status --json"],
    "rules add": [
        "finjuice rules add --dry-run --name dining_example --match example --tags 식비 --json"
    ],
}


def _first_paragraph(text: str | None) -> str:
    """Collapse the first paragraph of Click help text."""
    if not text:
        return ""

    paragraph_lines: list[str] = []
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)
    return " ".join(paragraph_lines)


def _schema_type(param: click.Parameter) -> str:
    """Return a compact type label from the shared JSON Schema mapper."""
    if param.nargs != 1 or getattr(param, "multiple", False):
        return "array"

    schema_type = base_type_schema(param).get("type", "string")
    if isinstance(schema_type, list):
        return "|".join(str(item) for item in schema_type)
    return str(schema_type)


def _short_option(param: click.Option) -> str | None:
    """Return the first short option alias, if present."""
    opts = [str(option) for option in (getattr(param, "opts", []) or [])]
    for option in opts:
        if option.startswith("-") and not option.startswith("--"):
            return option
    return None


def _envvar(param: click.Option) -> Any:
    """Return a JSON-serializable envvar declaration."""
    envvar = getattr(param, "envvar", None)
    return serialize_default(envvar)


def _argument_spec(param: click.Argument) -> dict[str, Any]:
    """Serialize a Click argument for the manifest."""
    return {
        "name": option_property_name(param),
        "type": _schema_type(param),
        "required": param.required,
        "default": serialize_default(param.default),
        "help": getattr(param, "help", None),
    }


def _option_spec(param: click.Option) -> dict[str, Any]:
    """Serialize a Click option for the manifest."""
    return {
        "name": option_property_name(param),
        "short": _short_option(param),
        "type": _schema_type(param),
        "default": serialize_default(param.default),
        "envvar": _envvar(param),
        "help": getattr(param, "help", None),
        "is_flag": bool(getattr(param, "is_flag", False)),
    }


def _privacy_profile(path: str) -> str:
    """Return the privacy profile advertised for a command path."""
    if path in ARTIFACT_COMMANDS:
        return "artifact_path"
    if path in RUNTIME_METADATA_COMMANDS:
        return "local_runtime_metadata"
    return "local_financial_data"


def _output_schema_ref(path: str, command: click.Command) -> str | None:
    """Return the conventional sibling JSON Schema artifact path for a command."""
    if not has_json_flag(command):
        return None
    return f"schemas/{path.replace(' ', '_')}.schema.json"


def _command_safety_metadata(path: str) -> dict[str, Any]:
    """Return additive agent safety metadata for one command path."""
    mutates_data = path in MUTATING_COMMANDS
    return {
        "safe_readonly": not mutates_data,
        "mutates_data": mutates_data,
        "requires_confirmation": path in CONFIRMATION_REQUIRED_COMMANDS,
        "privacy_profile": _privacy_profile(path),
        "examples": COMMAND_EXAMPLES.get(path, []),
        "error_schema_ref": ERROR_SCHEMA_REF,
    }


def _command_spec(
    dotted_path: str,
    command: click.Command,
    rich_help_panel: str | None,
) -> dict[str, Any]:
    """Serialize one visible leaf command."""
    path = dotted_path.replace(".", " ")
    arguments: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []

    for param in command.params:
        if getattr(param, "hidden", False):
            continue
        if isinstance(param, click.Argument):
            arguments.append(_argument_spec(param))
        elif isinstance(param, click.Option):
            options.append(_option_spec(param))

    return {
        "name": command.name or path.rsplit(" ", maxsplit=1)[-1],
        "path": path,
        "help": _first_paragraph(command.help or command.short_help),
        "rich_help_panel": rich_help_panel,
        "arguments": arguments,
        "options": options,
        "output_schema_ref": _output_schema_ref(path, command),
        **_command_safety_metadata(path),
    }


def _commands_only_spec(command: dict[str, Any]) -> dict[str, Any]:
    """Return the compact command description used by --commands-only."""
    return {
        "path": command["path"],
        "help_oneline": _first_paragraph(command.get("help")),
        "output_schema_ref": command["output_schema_ref"],
    }
