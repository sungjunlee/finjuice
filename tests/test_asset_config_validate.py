"""Identity tests for the asset_config payload-validator split."""

from pathlib import Path

from finjuice.pipeline import asset_config, asset_config_validate

PIPELINE_DIR = Path("src/finjuice/pipeline")

_PAYLOAD_VALIDATORS = (
    "_validate_assets_payload",
    "_validate_manual_assets",
    "_validate_liabilities",
)

_FIELD_HELPERS = (
    "_require_string",
    "_optional_string",
    "_require_number",
    "_optional_number",
    "_add_issue",
)


def test_payload_validators_live_in_validate_module() -> None:
    """Payload validators should not live in the main asset_config module."""
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")
    validate_text = (PIPELINE_DIR / "asset_config_validate.py").read_text(encoding="utf-8")

    assert "def load_assets_config" in config_text
    assert "class ManualAsset" in config_text
    assert "class Liability" in config_text
    assert "class AssetsConfig" in config_text
    assert "class AssetsConfigIssue" in config_text
    assert "class AssetsConfigValidationResult" in config_text
    assert "class AssetsConfigValidationError" in config_text

    for name in (*_PAYLOAD_VALIDATORS, *_FIELD_HELPERS):
        assert f"def {name}" not in config_text
        assert f"def {name}" in validate_text

    assert "def load_assets_config" not in validate_text
    assert "def validate_assets_config_file" not in validate_text
    assert "def validate_assets_config_file" not in config_text
    assert "class ManualAsset" not in validate_text
    assert "class AssetsConfig" not in validate_text
    assert "def _build_path_locations" not in validate_text
    assert "def _walk_node" not in validate_text


def test_payload_validators_reexport_from_asset_config() -> None:
    """Existing asset_config imports should keep resolving to the payload validators."""
    config_text = (PIPELINE_DIR / "asset_config.py").read_text(encoding="utf-8")

    for name in (*_PAYLOAD_VALIDATORS, *_FIELD_HELPERS):
        assert name in config_text
        assert getattr(asset_config, name) is getattr(asset_config_validate, name)

    assert asset_config._ASSET_TOP_LEVEL_KEYS is asset_config_validate._ASSET_TOP_LEVEL_KEYS
    assert asset_config._MANUAL_ASSET_KEYS is asset_config_validate._MANUAL_ASSET_KEYS
    assert asset_config._LIABILITY_KEYS is asset_config_validate._LIABILITY_KEYS
    assert callable(asset_config.load_assets_config)
    assert callable(asset_config.validate_assets_config_file)
    assert callable(asset_config._validate_assets_payload)
    assert callable(asset_config._validate_manual_assets)
    assert callable(asset_config._validate_liabilities)


def test_payload_validators_are_the_unique_home() -> None:
    """The moved cluster is defined exactly once, in asset_config_validate."""
    canonical = "finjuice.pipeline.asset_config_validate"

    assert asset_config_validate._validate_assets_payload.__module__ == canonical
    assert asset_config_validate._validate_manual_assets.__module__ == canonical
    assert asset_config_validate._validate_liabilities.__module__ == canonical
    assert asset_config_validate._require_string.__module__ == canonical
    assert asset_config_validate._optional_string.__module__ == canonical
    assert asset_config_validate._require_number.__module__ == canonical
    assert asset_config_validate._optional_number.__module__ == canonical
    assert asset_config_validate._add_issue.__module__ == canonical
    assert asset_config._validate_assets_payload.__module__ == canonical
    assert asset_config.load_assets_config.__module__ == "finjuice.pipeline.asset_config"
    assert (
        asset_config.validate_assets_config_file.__module__
        == "finjuice.pipeline.asset_config_helpers"
    )
    assert asset_config.AssetsConfig.__module__ == "finjuice.pipeline.asset_config"
    assert asset_config.ManualAsset.__module__ == "finjuice.pipeline.asset_config"
    assert asset_config.Liability.__module__ == "finjuice.pipeline.asset_config"
