"""Identity coverage for the goals_validators/fields helper split."""

from pathlib import Path

from finjuice.pipeline.goals_validators import fields, fields_helpers

GOALS_VALIDATORS_DIR = Path("src/finjuice/pipeline/goals_validators")

PROBLEM_HELPER_NAMES = (
    "_problem",
    "_parse_error_problem",
    "_position",
)


def test_problem_helpers_live_in_sibling_module() -> None:
    """Problem construction helpers should not live in the field-check module."""
    fields_text = (GOALS_VALIDATORS_DIR / "fields.py").read_text(encoding="utf-8")
    helpers_text = (GOALS_VALIDATORS_DIR / "fields_helpers.py").read_text(encoding="utf-8")

    assert "def _validate_required_label" in fields_text
    assert "def _validate_required_amount" in fields_text
    assert "def _validate_month_range" in fields_text
    assert "def _validate_date_range" in fields_text
    assert "def _validate_optional_tags" in fields_text
    for name in PROBLEM_HELPER_NAMES:
        assert f"def {name}" not in fields_text
        assert f"def {name}" in helpers_text


def test_problem_helpers_reexport_from_fields() -> None:
    """Existing fields.py imports should keep resolving to the problem helpers."""
    fields_text = (GOALS_VALIDATORS_DIR / "fields.py").read_text(encoding="utf-8")

    for name in PROBLEM_HELPER_NAMES:
        assert name in fields_text
        assert getattr(fields, name) is getattr(fields_helpers, name)

    assert callable(fields._validate_required_label)
    assert callable(fields._validate_required_amount)
    assert callable(fields._validate_month_range)
    assert callable(fields._validate_date_range)
    assert callable(fields._validate_optional_tags)
    assert callable(fields._problem)
    assert callable(fields._parse_error_problem)
    assert callable(fields._position)
