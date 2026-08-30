"""Financial-context section validators for goals.yaml.

Owns ``financial_context`` mapping/shape checks plus nested income, family,
and housing subsections. Field-level helpers stay in ``fields.py``. Payload
orchestration stays in ``validate.py``, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.goals_validators.fields import (
    _problem,
    _validate_optional_date,
    _validate_optional_non_negative_int,
    _validate_optional_positive_int,
    _validate_optional_string,
)
from finjuice.pipeline.goals_validators.models import (
    FamilyContext,
    FinancialContext,
    HousingContext,
    IncomeContext,
    ValidationProblems,
)


def _validate_financial_context(
    value: Any,
    problems: ValidationProblems,
) -> FinancialContext | None:
    """Validate optional high-level financial_context metadata."""
    if value is None:
        return None

    if not isinstance(value, dict):
        problems.append(_problem("financial_context", "must be a mapping", value))
        return None

    return FinancialContext(
        income=_validate_income_context(value.get("income"), value, problems),
        family=_validate_family_context(value.get("family"), value, problems),
        housing=_validate_housing_context(value.get("housing"), value, problems),
    )


def _validate_income_context(
    value: Any,
    parent: dict[Any, Any],
    problems: ValidationProblems,
) -> IncomeContext | None:
    """Validate optional financial_context.income metadata."""
    path = "financial_context.income"
    if value is None:
        return None
    if not isinstance(value, dict):
        problems.append(_problem(path, "must be a mapping", parent, key="income"))
        return None

    return IncomeContext(
        monthly_estimate=_validate_optional_non_negative_int(
            value,
            "monthly_estimate",
            path,
            problems,
        ),
        notes=_validate_optional_string(value, "notes", path, problems),
        source=_validate_optional_string(value, "source", path, problems),
        date=_validate_optional_date(value, "date", path, problems),
        as_of=_validate_optional_date(value, "as_of", path, problems),
    )


def _validate_family_context(
    value: Any,
    parent: dict[Any, Any],
    problems: ValidationProblems,
) -> FamilyContext | None:
    """Validate optional financial_context.family metadata."""
    path = "financial_context.family"
    if value is None:
        return None
    if not isinstance(value, dict):
        problems.append(_problem(path, "must be a mapping", parent, key="family"))
        return None

    return FamilyContext(
        household_size=_validate_optional_positive_int(value, "household_size", path, problems),
        dependents_count=_validate_optional_non_negative_int(
            value,
            "dependents_count",
            path,
            problems,
        ),
        notes=_validate_optional_string(value, "notes", path, problems),
        source=_validate_optional_string(value, "source", path, problems),
        date=_validate_optional_date(value, "date", path, problems),
        as_of=_validate_optional_date(value, "as_of", path, problems),
    )


def _validate_housing_context(
    value: Any,
    parent: dict[Any, Any],
    problems: ValidationProblems,
) -> HousingContext | None:
    """Validate optional financial_context.housing metadata."""
    path = "financial_context.housing"
    if value is None:
        return None
    if not isinstance(value, dict):
        problems.append(_problem(path, "must be a mapping", parent, key="housing"))
        return None

    status_value = value.get("status")
    if status_value is not None and (not isinstance(status_value, str) or not status_value.strip()):
        problems.append(
            _problem(f"{path}.status", "must be a non-empty string", value, key="status")
        )

    return HousingContext(
        status=status_value.strip() if isinstance(status_value, str) else None,
        monthly_payment=_validate_optional_non_negative_int(
            value,
            "monthly_payment",
            path,
            problems,
        ),
        deposit=_validate_optional_non_negative_int(value, "deposit", path, problems),
        notes=_validate_optional_string(value, "notes", path, problems),
        source=_validate_optional_string(value, "source", path, problems),
        date=_validate_optional_date(value, "date", path, problems),
        as_of=_validate_optional_date(value, "as_of", path, problems),
    )
