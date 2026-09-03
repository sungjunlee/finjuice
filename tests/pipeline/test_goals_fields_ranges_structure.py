"""Identity coverage for the goals_validators/fields date-range helper split."""

from pathlib import Path

from finjuice.pipeline.goals_validators import fields, fields_ranges

GOALS_VALIDATORS_DIR = Path("src/finjuice/pipeline/goals_validators")

RANGE_HELPER_NAMES = (
    "_validate_month_range",
    "_validate_date_range",
    "_validate_optional_month",
    "_validate_optional_date",
)


def test_date_range_helpers_live_in_sibling_module() -> None:
    """Date/month range helpers should not live in the scalar field-check module."""
    fields_text = (GOALS_VALIDATORS_DIR / "fields.py").read_text(encoding="utf-8")
    ranges_text = (GOALS_VALIDATORS_DIR / "fields_ranges.py").read_text(encoding="utf-8")

    assert "def _validate_required_label" in fields_text
    assert "def _validate_required_amount" in fields_text
    assert "def _validate_frequency" in fields_text
    assert "def _validate_optional_tags" in fields_text
    for name in RANGE_HELPER_NAMES:
        assert f"def {name}" not in fields_text
        assert f"def {name}" in ranges_text


def test_date_range_helpers_reexport_from_fields() -> None:
    """Existing fields.py imports should keep resolving to the range helpers."""
    fields_text = (GOALS_VALIDATORS_DIR / "fields.py").read_text(encoding="utf-8")

    for name in RANGE_HELPER_NAMES:
        assert name in fields_text
        assert getattr(fields, name) is getattr(fields_ranges, name)

    assert callable(fields._validate_required_label)
    assert callable(fields._validate_required_amount)
    assert callable(fields._validate_frequency)
    assert callable(fields._validate_optional_tags)
    assert callable(fields._validate_month_range)
    assert callable(fields._validate_date_range)
    assert callable(fields._validate_optional_month)
    assert callable(fields._validate_optional_date)
