"""Identity checks for the networth history helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import networth as networth_module
from finjuice.pipeline.cli.commands import networth_history

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "_history_as_of",
    "_build_history_rows",
)


def test_networth_history_helpers_live_in_helper_module() -> None:
    """History row assembly should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")
    history_text = (COMMANDS_DIR / "networth_history.py").read_text(encoding="utf-8")

    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    assert "def init_command" in command_text
    assert "def validate_command" in command_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in history_text


def test_networth_history_helpers_reexport_from_entrypoint() -> None:
    """Existing networth imports should keep resolving to the history helpers."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")

    assert "networth_app = typer.Typer" in command_text
    assert "def networth_callback" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(networth_module, name) is getattr(networth_history, name)

    assert callable(networth_module.networth_callback)
    assert callable(networth_module.breakdown)
    assert callable(networth_module.history)
    assert callable(networth_module.forecast)
    assert callable(networth_module.init_command)
    assert callable(networth_module.validate_command)
