"""Structure checks for the split networth assets.yaml helper implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import networth as networth_module
from finjuice.pipeline.cli.commands import networth_helpers

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "_emit_assets_file_json",
    "_assets_init_payload",
    "_write_starter_assets_yaml",
    "_build_validate_payload",
    "_run_init_command",
    "_run_validate_command",
)


def test_assets_file_helpers_live_in_helper_module() -> None:
    """assets.yaml init/validate helpers should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "networth_helpers.py").read_text(encoding="utf-8")

    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    assert "def init_command" in command_text
    assert "def validate_command" in command_text
    assert "def networth_callback" not in helpers_text

    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in helpers_text


def test_networth_helpers_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in networth_helpers."""
    canonical = "finjuice.pipeline.cli.commands.networth_helpers"

    for name in MOVED_HELPER_NAMES:
        assert getattr(networth_helpers, name).__module__ == canonical


def test_assets_file_helpers_reexport_from_entrypoint() -> None:
    """Existing networth imports should keep resolving to the helper definitions."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")

    assert "networth_app = typer.Typer" in command_text
    assert "def networth_callback" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(networth_module, name) is getattr(networth_helpers, name)

    assert callable(networth_module.networth_callback)
    assert callable(networth_module.breakdown)
    assert callable(networth_module.history)
    assert callable(networth_module.forecast)
    assert callable(networth_module.init_command)
    assert callable(networth_module.validate_command)
