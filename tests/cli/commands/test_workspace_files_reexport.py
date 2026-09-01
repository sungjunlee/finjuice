"""Identity checks for the workspace identity-file helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import workspace_cmd, workspace_files

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "write_workspace_metadata",
    "write_workspace_readme",
)


def test_workspace_file_helpers_live_in_helper_module() -> None:
    """Identity-file writers should not live in the Typer command."""
    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")
    files_text = (COMMANDS_DIR / "workspace_files.py").read_text(encoding="utf-8")

    assert "def workspace_create" in command_text
    assert "def workspace_remove" in command_text
    assert "def workspace_verify" in command_text
    assert "def workspace_open" in command_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in files_text


def test_workspace_file_helpers_reexport_from_entrypoint() -> None:
    """Existing workspace_cmd imports should keep resolving to the file helpers."""
    command_text = (COMMANDS_DIR / "workspace_cmd.py").read_text(encoding="utf-8")

    assert "def workspace_create" in command_text
    assert "def register_workspace_command" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(workspace_cmd, name) is getattr(workspace_files, name)

    assert callable(workspace_cmd.workspace_create)
    assert callable(workspace_cmd.workspace_list)
    assert callable(workspace_cmd.workspace_remove)
    assert callable(workspace_cmd.workspace_verify)
    assert callable(workspace_cmd.workspace_open)
    assert callable(workspace_cmd.register_workspace_command)
