"""Structure checks for the split inspect command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import inspect_cmd as inspect_module
from finjuice.pipeline.cli.commands import inspect_helpers

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_inspect_structure_helpers_live_in_helper_module() -> None:
    """Workbook walking and role/block detection should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "inspect_cmd.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "inspect_helpers.py").read_text(encoding="utf-8")

    assert "def inspect_xlsx_command" in command_text
    assert "inspect_app = typer.Typer" in command_text
    assert "def _render_xlsx_inspection" in command_text
    assert "def inspect_xlsx_structure" not in command_text
    assert "def _inspect_worksheet" not in command_text
    assert "def _collect_allowlisted_anchors" not in command_text
    assert "def _detect_roles" not in command_text
    assert "def _detect_blocks" not in command_text
    assert "def inspect_xlsx_structure" in helpers_text
    assert "def _inspect_worksheet" in helpers_text
    assert "def _collect_allowlisted_anchors" in helpers_text
    assert "def _detect_roles" in helpers_text
    assert "def _detect_blocks" in helpers_text


def test_inspect_public_names_stay_on_entrypoint() -> None:
    """The stable inspect import path should keep the command and extracted helper names."""
    command_text = (COMMANDS_DIR / "inspect_cmd.py").read_text(encoding="utf-8")

    assert "inspect_app = typer.Typer" in command_text
    assert "def inspect_xlsx_command" in command_text
    assert "inspect_xlsx_structure" in command_text
    assert "_inspect_worksheet" in command_text
    assert "_collect_allowlisted_anchors" in command_text
    assert "_detect_roles" in command_text
    assert "_detect_blocks" in command_text
    assert inspect_module.inspect_xlsx_structure is inspect_helpers.inspect_xlsx_structure
    assert inspect_module._inspect_worksheet is inspect_helpers._inspect_worksheet
    assert (
        inspect_module._collect_allowlisted_anchors is inspect_helpers._collect_allowlisted_anchors
    )
    assert inspect_module._detect_roles is inspect_helpers._detect_roles
    assert inspect_module._detect_blocks is inspect_helpers._detect_blocks
    assert callable(inspect_module.inspect_xlsx_command)
    assert callable(inspect_module.inspect_xlsx_structure)
