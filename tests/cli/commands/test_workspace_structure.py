"""Structure checks for the split workspace command implementation."""

from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_workspace_rendering_helpers_live_in_helper_module() -> None:
    """Create/list/remove/verify rendering should not live in the Typer command."""
    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "workspace_rendering.py").read_text(encoding="utf-8")

    assert "def workspace_create" in command_text
    assert "def workspace_list" in command_text
    assert "def workspace_remove" in command_text
    assert "def workspace_verify" in command_text
    assert "def workspace_open" in command_text
    assert "def get_open_command" in command_text
    assert "def _render_workspace_create_success" not in command_text
    assert "def _render_workspace_list" not in command_text
    assert "def _render_workspace_remove_warning" not in command_text
    assert "def _render_workspace_remove_success" not in command_text
    assert "def _render_workspace_verify" not in command_text
    assert "def _render_workspace_create_success" in rendering_text
    assert "def _render_workspace_list" in rendering_text
    assert "def _render_workspace_remove_warning" in rendering_text
    assert "def _render_workspace_remove_success" in rendering_text
    assert "def _render_workspace_verify" in rendering_text


def test_workspace_public_names_stay_on_entrypoint() -> None:
    """The stable workspace import path should keep public command and helper names."""
    from finjuice.pipeline.cli.commands import workspace_cmd, workspace_helpers, workspace_rendering

    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")

    assert "workspace_app = typer.Typer" in command_text
    assert "def workspace_create" in command_text
    assert "def workspace_list" in command_text
    assert "def workspace_remove" in command_text
    assert "def workspace_verify" in command_text
    assert "def workspace_open" in command_text
    assert "def get_open_command" in command_text
    assert "def register_workspace_command" in command_text
    assert "FILE_SYMLINKS" in command_text
    assert "SYMLINK_TARGETS" in command_text
    assert "WORKSPACE_VERSION" in command_text
    assert "create_symlinks" in command_text
    assert "is_valid_workspace" in command_text
    assert "_render_workspace_create_success" in command_text
    assert "_render_workspace_list" in command_text
    assert "_render_workspace_remove_warning" in command_text
    assert "_render_workspace_remove_success" in command_text
    assert "_render_workspace_verify" in command_text

    assert workspace_cmd.FILE_SYMLINKS is workspace_helpers.FILE_SYMLINKS
    assert workspace_cmd.SYMLINK_TARGETS is workspace_helpers.SYMLINK_TARGETS
    assert workspace_cmd.WORKSPACE_VERSION is workspace_helpers.WORKSPACE_VERSION
    assert workspace_cmd.create_symlinks is workspace_helpers.create_symlinks
    assert workspace_cmd.is_valid_workspace is workspace_helpers.is_valid_workspace
    assert (
        workspace_cmd._render_workspace_create_success
        is workspace_rendering._render_workspace_create_success
    )
    assert workspace_cmd._render_workspace_list is workspace_rendering._render_workspace_list
    assert (
        workspace_cmd._render_workspace_remove_warning
        is workspace_rendering._render_workspace_remove_warning
    )
    assert (
        workspace_cmd._render_workspace_remove_success
        is workspace_rendering._render_workspace_remove_success
    )
    assert workspace_cmd._render_workspace_verify is workspace_rendering._render_workspace_verify
    assert callable(workspace_cmd.get_open_command)
    assert callable(workspace_cmd.register_workspace_command)
