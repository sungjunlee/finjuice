"""Structure checks for the split networth command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import networth as networth_module
from finjuice.pipeline.cli.commands import (
    networth_errors,
    networth_forecast,
    networth_history,
    networth_payload,
)

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

CALLBACK_SURFACES = (
    ("_run_overview_command", networth_payload),
    ("_run_breakdown_command", networth_payload),
    ("_run_history_command", networth_history),
    ("_run_forecast_command", networth_forecast),
)


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


def test_subcommand_parsers_do_not_define_callback_bodies() -> None:
    """Payload/forecast/history callbacks must not leak into the Typer module."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")

    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    for name, sibling in CALLBACK_SURFACES:
        assert sibling.__file__ is not None
        sibling_text = Path(sibling.__file__).read_text(encoding="utf-8")
        assert f"def {name}" not in command_text
        assert f"def {name}" in sibling_text
        assert name in command_text


def test_callback_bodies_are_identity_reexports() -> None:
    """Extracted callbacks stay identity-equal on the networth entrypoint."""
    for name, sibling in CALLBACK_SURFACES:
        assert getattr(networth_module, name) is getattr(sibling, name)
        assert getattr(sibling, name).__module__ == sibling.__name__
        assert getattr(networth_module, name).__module__ == sibling.__name__

    assert networth_module.networth_callback is not networth_module._run_overview_command
    assert networth_module.breakdown is not networth_module._run_breakdown_command
    assert networth_module.history is not networth_module._run_history_command
    assert networth_module.forecast is not networth_module._run_forecast_command
