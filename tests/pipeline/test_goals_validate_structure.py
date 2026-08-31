"""Identity tests for the goals_validators/validate helper split."""

from pathlib import Path

from finjuice.pipeline.goals_validators import context, validate

GOALS_VALIDATORS_DIR = Path("src/finjuice/pipeline/goals_validators")


def test_financial_context_helpers_live_in_helper_module() -> None:
    """Financial-context section validators should not live in validate.py."""
    validate_text = (GOALS_VALIDATORS_DIR / "validate.py").read_text(encoding="utf-8")
    context_text = (GOALS_VALIDATORS_DIR / "context.py").read_text(encoding="utf-8")

    assert "def validate_goals_payload" in validate_text
    assert "def _validate_version" in validate_text
    assert "def _validate_recurring_savings" in validate_text
    assert "def _validate_known_obligations" in validate_text
    assert "def _validate_financial_context" not in validate_text
    assert "def _validate_income_context" not in validate_text
    assert "def _validate_family_context" not in validate_text
    assert "def _validate_housing_context" not in validate_text
    assert "def _validate_financial_context" in context_text
    assert "def _validate_income_context" in context_text
    assert "def _validate_family_context" in context_text
    assert "def _validate_housing_context" in context_text


def test_financial_context_helpers_reexport_from_validate() -> None:
    """Existing validate.py imports should keep resolving to the context helpers."""
    assert validate._validate_financial_context is context._validate_financial_context
    assert validate._validate_income_context is context._validate_income_context
    assert validate._validate_family_context is context._validate_family_context
    assert validate._validate_housing_context is context._validate_housing_context
    assert callable(validate.validate_goals_payload)
    assert callable(validate.validate_month_literal)
    assert callable(validate._validate_recurring_savings)
    assert callable(validate._validate_known_obligations)
