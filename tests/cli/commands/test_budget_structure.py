"""Structure checks for the split budget command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import budget as budget_module
from finjuice.pipeline.cli.commands import budget_rendering

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_budget_rendering_helpers_live_in_helper_module() -> None:
    """Status/edit/validate rendering should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "budget.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "budget_rendering.py").read_text(encoding="utf-8")

    assert "def budget_status_command" in command_text
    assert "def budget_edit_command" in command_text
    assert "def budget_validate_command" in command_text
    assert "def _raise_goals_validation_error" in command_text
    assert "def _render_budget_status" not in command_text
    assert "def _render_budget_edit" not in command_text
    assert "def _render_budget_validate" not in command_text
    assert "def _format_currency" not in command_text
    assert "def _style_status" not in command_text
    assert "def _format_progress" not in command_text
    assert "def _display_change_value" not in command_text
    assert "def _render_unmatched_goal_warning" not in command_text
    assert "def _render_budget_status" in rendering_text
    assert "def _render_budget_edit" in rendering_text
    assert "def _render_budget_validate" in rendering_text
    assert "def _format_currency" in rendering_text
    assert "def _style_status" in rendering_text
    assert "def _format_progress" in rendering_text
    assert "def _display_change_value" in rendering_text
    assert "def _render_unmatched_goal_warning" in rendering_text


def test_budget_rendering_helpers_reexport_from_entrypoint() -> None:
    """Existing budget.py imports should keep resolving to the rendering helpers."""
    command_text = (COMMANDS_DIR / "budget.py").read_text(encoding="utf-8")

    assert "budget_app = typer.Typer" in command_text
    assert "def budget_status_command" in command_text
    assert "def budget_edit_command" in command_text
    assert "def budget_validate_command" in command_text
    assert "BUDGET_SPEND_INCLUSION" in command_text
    assert "_render_budget_status" in command_text
    assert "_render_budget_edit" in command_text
    assert "_render_budget_validate" in command_text
    assert "_format_currency" in command_text
    assert "_style_status" in command_text
    assert "_format_progress" in command_text
    assert "_display_change_value" in command_text
    assert "_render_unmatched_goal_warning" in command_text

    assert budget_module.BUDGET_SPEND_INCLUSION is budget_rendering.BUDGET_SPEND_INCLUSION
    assert budget_module._render_budget_status is budget_rendering._render_budget_status
    assert budget_module._render_budget_edit is budget_rendering._render_budget_edit
    assert budget_module._render_budget_validate is budget_rendering._render_budget_validate
    assert budget_module._format_currency is budget_rendering._format_currency
    assert budget_module._style_status is budget_rendering._style_status
    assert budget_module._format_progress is budget_rendering._format_progress
    assert budget_module._display_change_value is budget_rendering._display_change_value
    assert (
        budget_module._render_unmatched_goal_warning
        is budget_rendering._render_unmatched_goal_warning
    )
    assert callable(budget_module.budget_status_command)
    assert callable(budget_module.budget_edit_command)
    assert callable(budget_module.budget_validate_command)
