"""Tests for the finjuice CLI tool schema generator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import typer

from finjuice.pipeline.cli.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "generate_tool_schema.py"


def load_generator_module() -> ModuleType:
    """Load the generator script as a Python module."""
    spec = importlib.util.spec_from_file_location("generate_tool_schema", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_executable_command(command: object) -> bool:
    """Return whether a Click command path can be invoked directly."""
    if getattr(command, "callback", None) is None:
        return False
    if getattr(command, "commands", None):
        return bool(getattr(command, "invoke_without_command", False))
    return True


def iter_expected_commands() -> set[str]:
    """Return all executable CLI commands from the live Click tree."""
    click_app = typer.main.get_command(app)
    expected: set[str] = set()

    def walk(prefix: str, group: object) -> None:
        if prefix and is_executable_command(group):
            expected.add(prefix)
        commands = getattr(group, "commands", {})
        for name in sorted(commands):
            command = commands[name]
            full_name = f"{prefix}.{name}" if prefix else name
            if getattr(command, "hidden", False):
                continue
            walk(full_name, command)

    walk("", click_app)
    return expected


def iter_expected_json_commands() -> set[str]:
    """Return all commands that expose a canonical --json flag."""
    click_app = typer.main.get_command(app)
    expected: set[str] = set()

    def walk(prefix: str, group: object) -> None:
        if (
            prefix
            and is_executable_command(group)
            and any(
                "--json" in getattr(param, "opts", []) for param in getattr(group, "params", [])
            )
        ):
            expected.add(prefix)
        commands = getattr(group, "commands", {})
        for name in sorted(commands):
            command = commands[name]
            full_name = f"{prefix}.{name}" if prefix else name
            if getattr(command, "hidden", False):
                continue
            walk(full_name, command)

    walk("", click_app)
    return expected


def generate_payload(tmp_path: Path) -> tuple[dict[str, object], Path]:
    """Generate a fresh tool schema payload into a temporary file."""
    module = load_generator_module()
    output_path = tmp_path / "tools.json"
    payload = module.generate_tool_schema(output_path)
    return payload, output_path


def test_generate_tool_schema_creates_valid_json(tmp_path: Path) -> None:
    """The generator should write valid JSON to disk."""
    payload, output_path = generate_payload(tmp_path)

    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_tools_json_has_all_commands(tmp_path: Path) -> None:
    """The generated tool list should cover every executable CLI command."""
    payload, _ = generate_payload(tmp_path)
    tools = payload["tools"]
    tool_names = {tool["name"] for tool in tools}

    assert tool_names == iter_expected_commands()
    assert {"status", "refresh", "tag", "export", "rules.validate", "query"} <= tool_names


def test_tool_parameters_match_cli(tmp_path: Path) -> None:
    """The generated status tool should expose the expected parameter names and types."""
    payload, _ = generate_payload(tmp_path)
    tools_by_name = {tool["name"]: tool for tool in payload["tools"]}

    status_tool = tools_by_name["status"]
    properties = status_tool["parameters"]["properties"]

    assert properties["detailed"]["type"] == "boolean"
    assert properties["detailed"]["default"] is False
    assert properties["top"]["type"] == "integer"
    assert properties["top"]["default"] == 5
    assert properties["json"]["type"] == "boolean"
    assert properties["json"]["default"] is False


def test_json_schema_draft7_compatible(tmp_path: Path) -> None:
    """The generated payload should use draft-7 style parameter schemas."""
    payload, _ = generate_payload(tmp_path)

    assert payload["$schema"] == "https://json-schema.org/draft-07/schema#"
    for tool in payload["tools"]:
        assert {"name", "description", "parameters", "output_schema"} <= tool.keys()
        parameters = tool["parameters"]
        assert parameters["type"] == "object"
        assert isinstance(parameters["properties"], dict)
        assert parameters["additionalProperties"] is False
        if "required" in parameters:
            assert isinstance(parameters["required"], list)


def test_output_schema_present_for_json_commands(tmp_path: Path) -> None:
    """Commands with --json should expose a lightweight output schema."""
    payload, _ = generate_payload(tmp_path)
    tools_by_name = {tool["name"]: tool for tool in payload["tools"]}
    json_commands = iter_expected_json_commands()

    for command_name in json_commands:
        assert tools_by_name[command_name]["output_schema"] is not None

    for command_name in tools_by_name:
        if command_name not in json_commands:
            assert tools_by_name[command_name]["output_schema"] is None


def test_idempotent_generation(tmp_path: Path) -> None:
    """Running the generator twice should produce byte-for-byte identical output."""
    module = load_generator_module()
    output_path = tmp_path / "tools.json"

    module.generate_tool_schema(output_path)
    first = output_path.read_text(encoding="utf-8")

    module.generate_tool_schema(output_path)
    second = output_path.read_text(encoding="utf-8")

    assert first == second
