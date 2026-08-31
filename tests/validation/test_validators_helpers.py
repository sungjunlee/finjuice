"""Identity coverage for the validation column-name helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.validation import validators, validators_helpers

VALIDATION_DIR = Path("src/finjuice/pipeline/validation")

COLUMN_HELPER_NAMES = (
    "MAX_COLUMN_NAME_LENGTH",
    "_sanitize_column_names",
    "_suggest_column_mapping",
)


def test_column_name_helpers_live_in_sibling_module() -> None:
    """Column-name helpers should not live in the XLSX validation module."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")
    helpers_text = (VALIDATION_DIR / "validators_helpers.py").read_text(encoding="utf-8")

    assert "def validate_banksalad_xlsx" in validators_text
    assert "def validate_banksalad_xlsx_polars" in validators_text
    assert "class ValidationResult" in validators_text
    assert "def _suggest_column_mapping" not in validators_text
    assert "def _sanitize_column_names" not in validators_text
    assert "MAX_COLUMN_NAME_LENGTH = " not in validators_text

    assert "def _suggest_column_mapping" in helpers_text
    assert "def _sanitize_column_names" in helpers_text
    assert "MAX_COLUMN_NAME_LENGTH = " in helpers_text


def test_column_name_helpers_reexport_from_validators() -> None:
    """Existing validators imports should keep resolving to the column-name helpers."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")

    for name in COLUMN_HELPER_NAMES:
        assert name in validators_text
        assert getattr(validators, name) is getattr(validators_helpers, name)

    assert callable(validators.validate_banksalad_xlsx)
    assert callable(validators.validate_banksalad_xlsx_polars)
    assert callable(validators._suggest_column_mapping)
    assert callable(validators._sanitize_column_names)
