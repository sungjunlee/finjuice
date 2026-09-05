"""Structure tests for the asset_config.py helper split.

YAML path-location helpers and assets.yaml file validation live in
``asset_config_helpers`` and must stay identity-equal when re-exported from
``asset_config``, so existing import paths and monkeypatches keep working
after the split. The split also keeps ``asset_config_helpers`` as the single
canonical home for the moved cluster.
"""

from __future__ import annotations

import importlib
from pathlib import Path

PIPELINE_DIR = Path("src/finjuice/pipeline")

HELPER_NAMES = (
    "_build_path_locations",
    "_walk_node",
    "_lookup_location",
    "_parent_path",
    "validate_assets_config_file",
)


def test_asset_config_reexports_helpers_identity() -> None:
    """Moved helpers stay on asset_config as re-exports after the split."""
    config = importlib.import_module("finjuice.pipeline.asset_config")
    helpers = importlib.import_module("finjuice.pipeline.asset_config_helpers")
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")

    for name in HELPER_NAMES:
        assert name in config_text
        assert getattr(config, name) is getattr(helpers, name)

    assert callable(config.load_assets_config)
    assert callable(config.validate_assets_config_file)
    assert config.AssetsConfig.__name__ == "AssetsConfig"


def test_asset_config_helpers_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in asset_config_helpers."""
    config = importlib.import_module("finjuice.pipeline.asset_config")
    helpers = importlib.import_module("finjuice.pipeline.asset_config_helpers")
    canonical = "finjuice.pipeline.asset_config_helpers"

    for name in HELPER_NAMES:
        assert getattr(helpers, name).__module__ == canonical
        assert getattr(config, name).__module__ == canonical

    assert config.load_assets_config.__module__ == "finjuice.pipeline.asset_config"
    assert config.AssetsConfig.__module__ == "finjuice.pipeline.asset_config"
    assert config.ManualAsset.__module__ == "finjuice.pipeline.asset_config"
    assert config.Liability.__module__ == "finjuice.pipeline.asset_config"


def test_file_validation_helpers_live_in_helper_module() -> None:
    """YAML location helpers and file validation should not live in asset_config.py."""
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")
    helpers_text = (PIPELINE_DIR / "asset_config_helpers.py").read_text(encoding="utf-8")

    assert "def load_assets_config" in config_text
    assert "class AssetsConfig" in config_text
    assert "class ManualAsset" in config_text
    assert "class Liability" in config_text
    for name in HELPER_NAMES:
        assert f"def {name}" not in config_text
        assert f"def {name}" in helpers_text
    assert "def load_assets_config" not in helpers_text
    assert "class AssetsConfig" not in helpers_text
    assert "class ManualAsset" not in helpers_text
    assert "class Liability" not in helpers_text
