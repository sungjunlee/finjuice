"""Structure checks for the split automation CLI implementation."""

from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_automation_payload_helpers_live_in_helper_module() -> None:
    """Typed payload serializers should not live in the Typer command module."""
    command_text = (COMMANDS_DIR / "automation.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "automation_helpers.py").read_text(encoding="utf-8")

    assert "def automation_run_command" in command_text
    assert "automation_app = typer.Typer" in command_text
    assert "def _build_automation_run_payload" in command_text
    assert "def _render_automation_run" in command_text
    assert "def _serialize_automation_run_payload" not in command_text
    assert "def _compact_automation_run_payload" not in command_text
    assert "def _serialize_automation_next_steps" not in command_text
    assert "def _serialize_automation_run_payload" in helpers_text
    assert "def _compact_automation_run_payload" in helpers_text
    assert "def _serialize_automation_next_steps" in helpers_text
    assert "class AutomationRunPayload" in helpers_text


def test_automation_public_names_stay_on_entrypoint() -> None:
    """The stable automation import path should keep public command and payload names."""
    command_text = (COMMANDS_DIR / "automation.py").read_text(encoding="utf-8")

    assert "def automation_run_command" in command_text
    assert "automation_app = typer.Typer" in command_text
    assert "_serialize_automation_run_payload" in command_text
    assert "_compact_automation_run_payload" in command_text
    assert "AutomationRunPayload" in command_text
