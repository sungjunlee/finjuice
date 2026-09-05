"""Identity tests for the asset_config helper split."""

from pathlib import Path

from finjuice.pipeline import asset_config, asset_config_helpers

PIPELINE_DIR = Path("src/finjuice/pipeline")


def test_location_helpers_live_in_helper_module() -> None:
    """YAML path-location helpers should not live in the main asset_config module."""
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")
    helpers_text = (PIPELINE_DIR / "asset_config_helpers.py").read_text(encoding="utf-8")

    assert "def load_assets_config" in config_text
    assert "class AssetsConfig" in config_text
    assert "def _build_path_locations" not in config_text
    assert "def _walk_node" not in config_text
    assert "def _lookup_location" not in config_text
    assert "def _parent_path" not in config_text
    assert "def validate_assets_config_file" not in config_text
    assert "def _build_path_locations" in helpers_text
    assert "def _walk_node" in helpers_text
    assert "def _lookup_location" in helpers_text
    assert "def _parent_path" in helpers_text
    assert "def validate_assets_config_file" in helpers_text


def test_location_helpers_reexport_from_asset_config() -> None:
    """Existing asset_config imports should keep resolving to the location helpers."""
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")

    assert "_build_path_locations" in config_text
    assert "_walk_node" in config_text
    assert "_lookup_location" in config_text
    assert "_parent_path" in config_text
    assert asset_config._build_path_locations is asset_config_helpers._build_path_locations
    assert asset_config._walk_node is asset_config_helpers._walk_node
    assert asset_config._lookup_location is asset_config_helpers._lookup_location
    assert asset_config._parent_path is asset_config_helpers._parent_path
    assert callable(asset_config.load_assets_config)
    assert callable(asset_config.validate_assets_config_file)
    assert callable(asset_config._validate_assets_payload)
