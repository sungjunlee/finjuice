"""Identity checks for the budget goals.yaml error-envelope helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import budget as budget_module
from finjuice.pipeline.cli.commands import budget_errors, budget_rendering

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = ("_raise_goals_validation_error",)


def test_budget_error_helpers_live_in_helper_module() -> None:
    """Goals.yaml validation envelopes should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "budget.py").read_text(encoding="utf-8")
    errors_text = (COMMANDS_DIR / "budget_errors.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "budget_rendering.py").read_text(encoding="utf-8")

    assert "def budget_status_command" in command_text
    assert "def budget_edit_command" in command_text
    assert "def budget_validate_command" in command_text
    assert "def _render_budget_status" not in command_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in errors_text
        assert f"def {name}" not in rendering_text

    assert "def _render_budget_status" in rendering_text
    assert "def _render_budget_edit" in rendering_text
    assert "def _render_budget_validate" in rendering_text


def test_budget_error_helpers_reexport_from_entrypoint() -> None:
    """Existing budget.py imports should keep resolving to the error helpers."""
    command_text = (COMMANDS_DIR / "budget.py").read_text(encoding="utf-8")

    assert "budget_app = typer.Typer" in command_text
    assert "def budget_status_command" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(budget_module, name) is getattr(budget_errors, name)

    assert budget_module._raise_goals_validation_error is (
        budget_errors._raise_goals_validation_error
    )
    assert callable(budget_module.budget_status_command)
    assert callable(budget_module.budget_edit_command)
    assert callable(budget_module.budget_validate_command)
    assert callable(budget_rendering._render_budget_status)
