"""Focused tests for the Phase 1 automation config scaffold."""

from pathlib import Path

from finjuice.pipeline.config import Config
from finjuice.pipeline.config_file import load_config, save_config
from finjuice.pipeline.config_schema import (
    AutomationConfig,
    AutomationThresholdsConfig,
    DataConfig,
    UserConfig,
)


def _set_home(monkeypatch, tmp_path: Path) -> Path:
    """Point Path.home() to an isolated temporary directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _primary_config_path(home: Path) -> Path:
    """Return the primary config path for a test home directory."""
    return home / ".finjuice" / "config.toml"


def test_automation_config_defaults_when_section_missing(tmp_path, monkeypatch):
    """Legacy config files should still load a stable automation object."""
    home = _set_home(monkeypatch, tmp_path)
    config_path = _primary_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[data]\ndirectory = "/test-data"\n')

    loaded = load_config()

    assert loaded is not None
    assert loaded.automation == AutomationConfig()
    assert "automation" not in loaded.to_dict()


def test_automation_config_reads_explicit_thresholds(tmp_path, monkeypatch):
    """Explicit automation values should parse from config.toml."""
    home = _set_home(monkeypatch, tmp_path)
    config_path = _primary_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "[data]",
                'directory = "/test-data"',
                "",
                "[automation]",
                "enabled = true",
                "",
                "[automation.thresholds]",
                "untagged_count = 7",
                "large_transaction = 450000",
                "",
            ]
        )
    )

    loaded = load_config()

    assert loaded is not None
    assert loaded.automation.enabled is True
    assert loaded.automation.thresholds.untagged_count == 7
    assert loaded.automation.thresholds.large_transaction == 450_000


def test_automation_config_round_trip_preserves_explicit_values(tmp_path, monkeypatch):
    """Save/load round-trips should preserve an explicit automation section."""
    _set_home(monkeypatch, tmp_path)
    config = UserConfig(
        data=DataConfig(directory="/roundtrip"),
        automation=AutomationConfig(
            enabled=True,
            thresholds=AutomationThresholdsConfig(
                untagged_count=12,
                large_transaction=900_000,
            ),
        ),
        _automation_explicit=True,
    )

    save_config(config)
    loaded = load_config()

    assert loaded is not None
    assert loaded.automation == config.automation
    assert loaded.to_dict()["automation"] == {
        "enabled": True,
        "thresholds": {"untagged_count": 12, "large_transaction": 900_000},
    }


def test_automation_config_from_env_exposes_stable_object(tmp_path, monkeypatch):
    """Config.from_env() should expose automation settings from the config file."""
    _set_home(monkeypatch, tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(untagged_count=5, large_transaction=700_000),
            ),
            _automation_explicit=True,
        )
    )
    monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
    monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

    config = Config.from_env()

    assert config.data_dir == Path("/configured-data")
    assert config.automation.enabled is True
    assert config.automation.thresholds.untagged_count == 5
    assert config.automation.thresholds.large_transaction == 700_000


def test_automation_config_survives_env_data_dir_override(tmp_path, monkeypatch):
    """Higher-precedence FINJUICE_DATA_DIR should not discard automation settings."""
    _set_home(monkeypatch, tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=8,
                    large_transaction=850_000,
                ),
            ),
            _automation_explicit=True,
        )
    )
    monkeypatch.setenv("FINJUICE_DATA_DIR", "/env-data")
    monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

    config = Config.from_env()

    assert config.data_dir == Path("/env-data")
    assert config.automation.enabled is True
    assert config.automation.thresholds.untagged_count == 8
    assert config.automation.thresholds.large_transaction == 850_000


def test_automation_config_survives_explicit_data_dir_override(tmp_path, monkeypatch):
    """Explicit data_dir should override only the path, not automation defaults."""
    _set_home(monkeypatch, tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=3,
                    large_transaction=1_200_000,
                ),
            ),
            _automation_explicit=True,
        )
    )
    monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
    monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

    config = Config.from_env(data_dir="/cli-data")

    assert config.data_dir == Path("/cli-data")
    assert config.automation.enabled is True
    assert config.automation.thresholds.untagged_count == 3
    assert config.automation.thresholds.large_transaction == 1_200_000
