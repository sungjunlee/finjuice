"""Identity coverage for the validation pre-load helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.validation import validators, validators_preflight

VALIDATION_DIR = Path("src/finjuice/pipeline/validation")

PREFLIGHT_HELPER_NAMES = (
    "MAX_FILE_SIZE_MB",
    "_sheet_name_error_message",
    "_missing_file_error_message",
    "_oversized_file_error_message",
)


def test_preflight_helpers_live_in_sibling_module() -> None:
    """Pre-load file/sheet guards should not live in the XLSX validation module."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")
    helpers_text = (VALIDATION_DIR / "validators_helpers.py").read_text(encoding="utf-8")
    preflight_text = (VALIDATION_DIR / "validators_preflight.py").read_text(encoding="utf-8")

    assert "def validate_banksalad_xlsx" in validators_text
    assert "def validate_banksalad_xlsx_polars" in validators_text
    assert "class ValidationResult" in validators_text
    assert "def _sheet_name_error_message" not in validators_text
    assert "def _missing_file_error_message" not in validators_text
    assert "def _oversized_file_error_message" not in validators_text
    assert "MAX_FILE_SIZE_MB = " not in validators_text

    assert "def _suggest_column_mapping" in helpers_text
    assert "def _sanitize_column_names" in helpers_text
    assert "MAX_COLUMN_NAME_LENGTH = " in helpers_text
    assert "def _sheet_name_error_message" not in helpers_text
    assert "MAX_FILE_SIZE_MB = " not in helpers_text

    assert "def _sheet_name_error_message" in preflight_text
    assert "def _missing_file_error_message" in preflight_text
    assert "def _oversized_file_error_message" in preflight_text
    assert "MAX_FILE_SIZE_MB = " in preflight_text


def test_preflight_helpers_reexport_from_validators() -> None:
    """Existing validators imports should keep resolving to the preflight helpers."""
    validators_text = (VALIDATION_DIR / "validators.py").read_text(encoding="utf-8")

    for name in PREFLIGHT_HELPER_NAMES:
        assert name in validators_text
        assert getattr(validators, name) is getattr(validators_preflight, name)

    assert callable(validators.validate_banksalad_xlsx)
    assert callable(validators.validate_banksalad_xlsx_polars)
    assert callable(validators._sheet_name_error_message)
    assert callable(validators._missing_file_error_message)
    assert callable(validators._oversized_file_error_message)
