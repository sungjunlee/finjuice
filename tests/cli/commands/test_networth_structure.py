"""Structure checks for the split networth command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import networth as networth_module
from finjuice.pipeline.cli.commands import networth_errors

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_networth_error_helpers_live_in_helper_module() -> None:
    """Validation and runtime error envelopes should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")
    errors_text = (COMMANDS_DIR / "networth_errors.py").read_text(encoding="utf-8")

    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    assert "def init_command" in command_text
    assert "def validate_command" in command_text
    assert "def _validation_issue_to_problem" not in command_text
    assert "def _raise_goals_validation_error" not in command_text
    assert "def _handle_networth_exception" not in command_text
    assert "def _validation_issue_to_problem" in errors_text
    assert "def _raise_goals_validation_error" in errors_text
    assert "def _handle_networth_exception" in errors_text


def test_networth_public_names_stay_on_entrypoint() -> None:
    """The stable networth import path should keep command and extracted helper names."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")

    assert "networth_app = typer.Typer" in command_text
    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    assert "def init_command" in command_text
    assert "def validate_command" in command_text
    assert "_validation_issue_to_problem" in command_text
    assert "_raise_goals_validation_error" in command_text
    assert "_handle_networth_exception" in command_text
    assert (
        networth_module._validation_issue_to_problem is networth_errors._validation_issue_to_problem
    )
    assert (
        networth_module._raise_goals_validation_error
        is networth_errors._raise_goals_validation_error
    )
    assert networth_module._handle_networth_exception is networth_errors._handle_networth_exception
    assert callable(networth_module.networth_callback)
    assert callable(networth_module.breakdown)
    assert callable(networth_module.history)
    assert callable(networth_module.forecast)
    assert callable(networth_module.init_command)
    assert callable(networth_module.validate_command)
