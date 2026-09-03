"""Identity coverage for the validation XLSX-load helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.validation import validators, validators_load

VALIDATION_DIR = Path("src/finjuice/pipeline/validation")

LOAD_HELPER_NAMES = (
    "_load_banksalad_xlsx",
    "_xlsx_load_error_message",
)


def test_load_helpers_live_in_sibling_module() -> None:
    """Workbook load helpers should not live in the XLSX validation module."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")
    helpers_text = (VALIDATION_DIR / "validators_helpers.py").read_text(encoding="utf-8")
    preflight_text = (VALIDATION_DIR / "validators_preflight.py").read_text(encoding="utf-8")
    load_text = (VALIDATION_DIR / "validators_load.py").read_text(encoding="utf-8")

    assert "def validate_banksalad_xlsx" in validators_text
    assert "def validate_banksalad_xlsx_polars" in validators_text
    assert "class ValidationResult" in validators_text
    assert "def _load_banksalad_xlsx" not in validators_text
    assert "def _xlsx_load_error_message" not in validators_text

    assert "def _suggest_column_mapping" in helpers_text
    assert "def _sanitize_column_names" in helpers_text
    assert "MAX_COLUMN_NAME_LENGTH = " in helpers_text
    assert "def _sheet_name_error_message" in preflight_text
    assert "MAX_FILE_SIZE_MB = " in preflight_text
    assert "def _load_banksalad_xlsx" not in helpers_text
    assert "def _load_banksalad_xlsx" not in preflight_text
    assert "def _xlsx_load_error_message" not in helpers_text
    assert "def _xlsx_load_error_message" not in preflight_text

    assert "def _load_banksalad_xlsx" in load_text
    assert "def _xlsx_load_error_message" in load_text
    assert "def validate_banksalad_xlsx" not in load_text
    assert "def _suggest_column_mapping" not in load_text
    assert "def _sheet_name_error_message" not in load_text


def test_load_helpers_reexport_from_validators() -> None:
    """Existing validators imports should keep resolving to the load helpers."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")

    for name in LOAD_HELPER_NAMES:
        assert name in validators_text
        assert getattr(validators, name) is getattr(validators_load, name)

    assert callable(validators.validate_banksalad_xlsx)
    assert callable(validators.validate_banksalad_xlsx_polars)
    assert callable(validators._load_banksalad_xlsx)
    assert callable(validators._xlsx_load_error_message)
