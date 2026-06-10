"""Tests for the CLI manifest self-description command."""

import json

import typer
from typer.testing import CliRunner

from finjuice import __version__
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import error_code_values, exit_code_items

runner = CliRunner()

REQUIRED_DISCOVERY_COMMANDS = {
    "status",
    "query",
    "tag",
    "rules add",
    "rules suggest",
    "template run",
    "review",
}


def _manifest_payload(*args: str) -> dict[str, object]:
    result = runner.invoke(app, ["manifest", "--json", *args])

    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_manifest_json_returns_required_top_level_keys() -> None:
    """`finjuice manifest --json` emits the expected machine-readable envelope."""
    payload = _manifest_payload()

    assert payload["_meta"]["command"] == "manifest"  # type: ignore[index]
    assert payload["_meta"]["schema_version"] == "1.0"  # type: ignore[index]
    assert payload["manifest_schema_version"] == "1.0"
    assert payload["finjuice_version"] == __version__
    assert isinstance(payload["commands"], list)
    assert isinstance(payload["error_codes"], list)
    assert isinstance(payload["exit_codes"], dict)
    assert isinstance(payload["panels"], list)
    assert payload["panels"] == ["Admin", "Advanced", "Analysis", "Commands"]
    assert all(
        command["rich_help_panel"] is None or isinstance(command["rich_help_panel"], str)
        for command in payload["commands"]
    )


def test_manifest_commands_match_introspected_executable_commands() -> None:
    """Every visible executable command discovered by Typer appears in the manifest."""
    import typer.main

    click_app = typer.main.get_command(app)

    def is_executable(command: object) -> bool:
        if getattr(command, "callback", None) is None:
            return False
        if getattr(command, "commands", None):
            return bool(getattr(command, "invoke_without_command", False))
        return True

    def walk(command: object, path: tuple[str, ...] = ()) -> set[str]:
        command_paths: set[str] = set()
        if path and is_executable(command):
            command_paths.add(" ".join(path))
        for name, subcommand in sorted(getattr(command, "commands", {}).items()):
            if getattr(subcommand, "hidden", False):
                continue
            command_paths.update(walk(subcommand, (*path, name)))
        return command_paths

    expected_paths = walk(click_app)
    payload = _manifest_payload()
    actual_paths = {command["path"] for command in payload["commands"]}  # type: ignore[index]

    assert expected_paths == actual_paths


def test_manifest_json_includes_agent_discovery_canary_commands() -> None:
    """Agents rely on a minimum CLI/API discovery set, not just the root command."""
    payload = _manifest_payload()
    actual_paths = {command["path"] for command in payload["commands"]}  # type: ignore[index]

    assert REQUIRED_DISCOVERY_COMMANDS <= actual_paths


def test_manifest_error_and_exit_codes_round_trip() -> None:
    """ErrorCode and ExitCode class attributes are exposed without hardcoding."""
    payload = _manifest_payload()

    expected_error_codes = sorted(error_code_values())
    expected_exit_codes = dict(exit_code_items())

    assert payload["error_codes"] == expected_error_codes
    assert payload["exit_codes"] == expected_exit_codes
    assert payload["error_schema_ref"] == "schemas/_error.schema.json"


def test_manifest_exposes_global_options_and_root_env() -> None:
    """Agents can discover root flags and env vars from one manifest payload."""
    payload = _manifest_payload()
    global_options = {option["name"]: option for option in payload["global_options"]}  # type: ignore[index]
    root_env = {item["name"]: item for item in payload["root_env"]}  # type: ignore[index]

    assert "data_dir" in global_options
    assert global_options["data_dir"]["envvar"] == "FINJUICE_DATA_DIR"
    assert "no_filter" in global_options
    assert global_options["no_filter"]["is_flag"] is True
    assert root_env["FINJUICE_DATA_DIR"]["option"] == "--data-dir"


def test_manifest_exposes_command_safety_metadata() -> None:
    """Agents can distinguish read-only and mutating commands from manifest JSON."""
    payload = _manifest_payload()
    commands = {command["path"]: command for command in payload["commands"]}  # type: ignore[index]

    assert commands["status"]["safe_readonly"] is True
    assert commands["status"]["mutates_data"] is False
    assert commands["status"]["requires_confirmation"] is False
    assert commands["status"]["privacy_profile"] == "local_financial_data"

    assert commands["automation run"]["safe_readonly"] is True
    assert commands["automation run"]["mutates_data"] is False
    assert commands["automation run"]["requires_confirmation"] is False

    assert commands["rules add"]["safe_readonly"] is False
    assert commands["rules add"]["mutates_data"] is True
    assert commands["rules add"]["requires_confirmation"] is True
    assert commands["rules add"]["error_schema_ref"] == "schemas/_error.schema.json"

    assert commands["doctor"]["safe_readonly"] is False
    assert commands["doctor"]["mutates_data"] is True

    assert commands["rules suggest"]["safe_readonly"] is False
    assert commands["rules suggest"]["mutates_data"] is True
    assert commands["rules suggest"]["requires_confirmation"] is True

    assert commands["rules export"]["safe_readonly"] is False
    assert commands["rules export"]["mutates_data"] is True

    assert commands["rules gaps"]["safe_readonly"] is False
    assert commands["rules gaps"]["mutates_data"] is True

    assert commands["template run"]["safe_readonly"] is False
    assert commands["template run"]["mutates_data"] is True

    assert commands["export"]["privacy_profile"] == "artifact_path"
    assert "local_financial_data" in payload["privacy_profiles"]  # type: ignore[operator]
    assert payload["examples"]  # type: ignore[index]


def test_manifest_commands_only_is_smaller_and_minimal() -> None:
    """`--commands-only` strips parameter and exit/error detail."""
    full_result = runner.invoke(app, ["manifest", "--json"])
    minimal_result = runner.invoke(app, ["manifest", "--json", "--commands-only"])

    assert full_result.exit_code == 0, full_result.output
    assert minimal_result.exit_code == 0, minimal_result.output
    assert len(minimal_result.output) < len(full_result.output)

    payload = json.loads(minimal_result.output)
    assert "error_codes" not in payload
    assert "exit_codes" not in payload
    assert set(payload) == {"_meta", "manifest_schema_version", "finjuice_version", "commands"}
    assert all(
        set(command) == {"path", "help_oneline", "output_schema_ref"}
        for command in payload["commands"]
    )
    assert REQUIRED_DISCOVERY_COMMANDS <= {command["path"] for command in payload["commands"]}


def test_manifest_introspection_picks_up_new_dummy_command() -> None:
    """A newly registered Typer command appears without manual manifest changes."""
    from finjuice.pipeline.cli.commands.manifest import _build_manifest

    dummy_app = typer.Typer()

    @dummy_app.command("demo", help="Demo command.", rich_help_panel="Admin")
    def demo(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ) -> None:
        pass

    manifest = _build_manifest(dummy_app, commands_only=False)

    assert any(command["path"] == "demo" for command in manifest["commands"])


def test_manifest_schema_ref_convention_for_json_commands() -> None:
    """Commands exposing --json point to sibling schema artifact paths."""
    payload = _manifest_payload()
    refs = [
        (command["path"], command["output_schema_ref"])
        for command in payload["commands"]  # type: ignore[index]
        if command["output_schema_ref"] is not None
    ]

    assert refs
    for path, schema_ref in refs:
        assert schema_ref == f"schemas/{path.replace(' ', '_')}.schema.json"
