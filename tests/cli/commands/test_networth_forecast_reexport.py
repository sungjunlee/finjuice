"""Identity checks for the networth forecast helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands import networth as networth_module
from finjuice.pipeline.cli.commands import networth_forecast

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "_forecast_start_as_of",
    "_serialize_forecast_scenario",
    "_build_all_scenario_forecasts",
)


def test_networth_forecast_helpers_live_in_helper_module() -> None:
    """Forecast scenario serialization should not live in the Typer module."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")
    forecast_text = (COMMANDS_DIR / "networth_forecast.py").read_text(encoding="utf-8")

    assert "def networth_callback" in command_text
    assert "def breakdown" in command_text
    assert "def history" in command_text
    assert "def forecast" in command_text
    assert "def init_command" in command_text
    assert "def validate_command" in command_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in command_text
        assert f"def {name}" in forecast_text


def test_networth_forecast_helpers_reexport_from_entrypoint() -> None:
    """Existing networth imports should keep resolving to the forecast helpers."""
    command_text = (COMMANDS_DIR / "networth.py").read_text(encoding="utf-8")

    assert "networth_app = typer.Typer" in command_text
    assert "def networth_callback" in command_text
    for name in MOVED_HELPER_NAMES:
        assert name in command_text
        assert getattr(networth_module, name) is getattr(networth_forecast, name)

    assert callable(networth_module.networth_callback)
    assert callable(networth_module.breakdown)
    assert callable(networth_module.history)
    assert callable(networth_module.forecast)
    assert callable(networth_module.init_command)
    assert callable(networth_module.validate_command)
