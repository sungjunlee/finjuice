"""Identity checks for the workspace file-manager launch helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import workspace_cmd, workspace_launch

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "get_open_command",
    "open_workspace_path",
)


def test_workspace_launch_helpers_live_in_helper_module() -> None:
    """File-manager launch helpers should not live in the Typer command."""
    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")
    launch_text = (COMMANDS_DIR / "workspace_launch.py").read_text(encoding="utf-8")

    assert "def workspace_create" in command_text
    assert "def workspace_remove" in command_text
    assert "def workspace_verify" in command_text
    assert "def workspace_open" in command_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in launch_text


def test_workspace_launch_helpers_reexport_from_entrypoint() -> None:
    """Existing workspace_cmd imports should keep resolving to the launch helpers."""
    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")

    assert "def workspace_create" in command_text
    assert "def register_workspace_command" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(workspace_cmd, name) is getattr(workspace_launch, name)

    assert callable(workspace_cmd.workspace_create)
    assert callable(workspace_cmd.workspace_list)
    assert callable(workspace_cmd.workspace_remove)
    assert callable(workspace_cmd.workspace_verify)
    assert callable(workspace_cmd.workspace_open)
    assert callable(workspace_cmd.register_workspace_command)
