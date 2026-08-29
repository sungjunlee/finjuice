"""Section-level validation rules for goals.yaml payload.

Field-level helpers live in ``fields.py`` and are re-exported from this package.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.goals_validators.fields import (
    _is_non_negative_int,
    _parse_error_problem,  # noqa: F401 — re-exported for existing validate.py imports
    _position,  # noqa: F401 — re-exported for existing validate.py imports
    _problem,
    _validate_date_range,
    _validate_frequency,
    _validate_month_range,
    _validate_optional_date,
    _validate_optional_month,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_optional_non_negative_int,
    _validate_optional_positive_int,
    _validate_optional_string,
    _validate_optional_tags,
    _validate_required_amount,
    _validate_required_label,
)
from finjuice.pipeline.goals_validators.models import (
    DATE_LITERAL_PATTERN,
    MONTH_LITERAL_PATTERN,
    FamilyContext,
    FinancialContext,
    GoalsDocument,
    HousingContext,
    IncomeContext,
    KnownObligation,
    MonthlyBudget,
    RecurringSavingsGoal,
    ValidationProblems,
)


def validate_goals_payload(
    payload: Any,
) -> tuple[GoalsDocument | None, ValidationProblems]:
    """Validate a parsed goals payload."""
    problems: ValidationProblems = []

    if not isinstance(payload, dict):
        problems.append(_problem("goals.yaml", "must contain a mapping", payload))
        return None, problems

    _validate_version(payload, problems)
    budget_value = _validate_monthly_budget_mapping(payload, problems)
    if budget_value is None:
        return None, problems

    monthly_budget = _validate_monthly_budget(budget_value, problems)
    target_value = _validate_net_worth_target(payload, problems)

    recurring_savings = _validate_recurring_savings(payload.get("recurring_savings"), problems)
    financial_context = _validate_financial_context(payload.get("financial_context"), problems)
    known_obligations = _validate_known_obligations(payload.get("known_obligations"), problems)

    if problems or monthly_budget is None:
        return None, problems

    document = GoalsDocument(
        version=1,
        monthly_budget=monthly_budget,
        net_worth_target=target_value,
        recurring_savings=recurring_savings,
        financial_context=financial_context,
        known_obligations=known_obligations,
    )
    return document, []


def _validate_version(payload: dict[Any, Any], problems: ValidationProblems) -> None:
    """Validate the required goals schema version."""
    version_value = payload.get("version")
    if version_value is None:
        problems.append(_problem("version", "missing required key", payload))
    elif type(version_value) is not int or version_value != 1:
        problems.append(_problem("version", "must be integer 1", payload, key="version"))


def _validate_monthly_budget_mapping(
    payload: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[Any, Any] | None:
    """Return the monthly_budget mapping or record a fatal section problem."""
    budget_value = payload.get("monthly_budget")
    if budget_value is None:
        problems.append(_problem("monthly_budget", "missing required key", payload))
        return None
    if not isinstance(budget_value, dict):
        problems.append(
            _problem("monthly_budget", "must be a mapping", payload, key="monthly_budget")
        )
        return None
    return budget_value


def _validate_monthly_budget(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> MonthlyBudget | None:
    """Validate the required monthly_budget section."""
    total = _validate_budget_total(budget_value, problems)
    categories = _validate_budget_categories(budget_value, problems)
    updated = _validate_budget_updated(budget_value, problems)
    notes = _validate_budget_notes(budget_value, problems)
    if total is None or categories is None:
        return None
    return MonthlyBudget(total=total, categories=categories, updated=updated, notes=notes)


def _validate_budget_total(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> int | None:
    """Validate monthly_budget.total."""
    total_value = budget_value.get("total")
    if total_value is None:
        problems.append(_problem("monthly_budget.total", "missing required key", budget_value))
        return None
    if not _is_non_negative_int(total_value):
        problems.append(
            _problem(
                "monthly_budget.total",
                "must be a non-negative integer",
                budget_value,
                key="total",
            )
        )
        return None
    return int(total_value)


def _validate_budget_categories(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[str, int] | None:
    """Validate monthly_budget.categories."""
    categories_value = budget_value.get("categories")
    if categories_value is None:
        problems.append(_problem("monthly_budget.categories", "missing required key", budget_value))
        return None
    if not isinstance(categories_value, dict):
        problems.append(
            _problem(
                "monthly_budget.categories",
                "must be a mapping of category name -> non-negative integer",
                budget_value,
                key="categories",
            )
        )
        return None
    return _validate_budget_category_values(categories_value, problems)


def _validate_budget_category_values(
    categories_value: dict[Any, Any],
    problems: ValidationProblems,
) -> dict[str, int]:
    """Validate each category target in monthly_budget.categories."""
    categories: dict[str, int] = {}
    for category_name, amount in categories_value.items():
        category_path = f"monthly_budget.categories.{category_name}"
        if not isinstance(category_name, str) or not category_name.strip():
            problems.append(
                _problem(
                    "monthly_budget.categories",
                    "category names must be non-empty strings",
                    categories_value,
                    key=category_name,
                )
            )
            continue
        if not _is_non_negative_int(amount):
            problems.append(
                _problem(
                    category_path,
                    "must be a non-negative integer",
                    categories_value,
                    key=category_name,
                )
            )
            continue
        categories[category_name] = int(amount)
    return categories


def _validate_budget_updated(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> str | None:
    """Validate monthly_budget.updated."""
    updated_value = budget_value.get("updated")
    if updated_value is None:
        return None
    if not isinstance(updated_value, str) or not DATE_LITERAL_PATTERN.match(updated_value):
        problems.append(
            _problem(
                "monthly_budget.updated",
                "must use YYYY-MM-DD format",
                budget_value,
                key="updated",
            )
        )
        return None
    try:
        date.fromisoformat(updated_value)
    except ValueError:
        problems.append(
            _problem(
                "monthly_budget.updated",
                "must be a real calendar date in YYYY-MM-DD format",
                budget_value,
                key="updated",
            )
        )
        return None
    return updated_value


def _validate_budget_notes(
    budget_value: dict[Any, Any],
    problems: ValidationProblems,
) -> str | None:
    """Validate monthly_budget.notes."""
    notes_value = budget_value.get("notes")
    if notes_value is None:
        return None
    if not isinstance(notes_value, str):
        problems.append(
            _problem(
                "monthly_budget.notes",
                "must be a string",
                budget_value,
                key="notes",
            )
        )
        return None
    return notes_value


def _validate_net_worth_target(
    payload: dict[Any, Any],
    problems: ValidationProblems,
) -> int | None:
    """Validate optional net_worth_target."""
    target_value = payload.get("net_worth_target")
    if target_value is None:
        return None
    if not _is_non_negative_int(target_value):
        problems.append(
            _problem(
                "net_worth_target",
                "must be a non-negative integer",
                payload,
                key="net_worth_target",
            )
        )
        return None
    return int(target_value)


def validate_month_literal(raw: str, *, param_name: str = "month") -> str:
    """Validate a YYYY-MM month literal."""
    if not MONTH_LITERAL_PATTERN.match(raw):
        raise ValueError(f"Invalid month value for '{param_name}': {raw} (expected YYYY-MM)")
    return raw


def _validate_recurring_savings(
    value: Any,
    problems: ValidationProblems,
) -> list[RecurringSavingsGoal]:
    """Validate the optional recurring_savings list."""
    if value is None:
        return []

    if not isinstance(value, list):
        problems.append(_problem("recurring_savings", "must be a list", value))
        return []

    entries: list[RecurringSavingsGoal] = []
    for index, item in enumerate(value):
        path = f"recurring_savings[{index}]"
        if not isinstance(item, dict):
            problems.append(_problem(path, "must be a mapping", value, key=index))
            continue
        entry = _validate_recurring_savings_item(item, path, problems)
        if entry is not None:
            entries.append(entry)

    return entries


def _validate_recurring_savings_item(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> RecurringSavingsGoal | None:
    """Validate one recurring_savings entry."""
    problem_count = len(problems)
    label = _validate_required_label(item, path, problems)
    amount = _validate_required_amount(item, path, problems)
    frequency = _validate_frequency(item, path, problems)
    start_month, end_month = _validate_month_range(item, path, problems)
    start_date, end_date = _validate_date_range(item, path, problems)
    tags = _validate_optional_tags(item.get("tags"), f"{path}.tags", item, problems)
    notes_value = _validate_optional_string(item, "notes", path, problems)
    source_value = _validate_optional_string(item, "source", path, problems)

    if len(problems) != problem_count or label is None or amount is None or frequency is None:
        return None

    return RecurringSavingsGoal(
        label=label,
        amount=amount,
        frequency=frequency,
        tags=tags,
        notes=notes_value,
        source=source_value,
        start_month=start_month,
        end_month=end_month,
        start_date=start_date,
        end_date=end_date,
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


def _validate_known_obligations(
    value: Any,
    problems: ValidationProblems,
) -> list[KnownObligation]:
    """Validate optional known_obligations metadata."""
    if value is None:
        return []

    if not isinstance(value, list):
        problems.append(_problem("known_obligations", "must be a list", value))
        return []

    entries: list[KnownObligation] = []
    for index, item in enumerate(value):
        path = f"known_obligations[{index}]"
        if not isinstance(item, dict):
            problems.append(_problem(path, "must be a mapping", value, key=index))
            continue
        entry = _validate_known_obligation_item(item, path, problems)
        if entry is not None:
            entries.append(entry)

    return entries


def _validate_known_obligation_item(
    item: dict[Any, Any],
    path: str,
    problems: ValidationProblems,
) -> KnownObligation | None:
    """Validate one known_obligations entry."""
    problem_count = len(problems)
    label = _validate_required_label(item, path, problems)
    amount = _validate_required_amount(item, path, problems)
    frequency = _validate_frequency(item, path, problems)
    kind_value = _validate_optional_string(item, "kind", path, problems)
    category_value = _validate_optional_string(item, "category", path, problems)
    notes_value = _validate_optional_string(item, "notes", path, problems)
    source_value = _validate_optional_string(item, "source", path, problems)
    date_value = _validate_optional_date(item, "date", path, problems)
    as_of_value = _validate_optional_date(item, "as_of", path, problems)
    start_month, end_month = _validate_month_range(item, path, problems)
    start_date, end_date = _validate_date_range(item, path, problems)

    if len(problems) != problem_count or label is None or amount is None or frequency is None:
        return None

    return KnownObligation(
        label=label,
        amount=amount,
        frequency=frequency,
        kind=kind_value,
        category=category_value,
        notes=notes_value,
        source=source_value,
        date=date_value,
        as_of=as_of_value,
        start_month=start_month,
        end_month=end_month,
        start_date=start_date,
        end_date=end_date,
    )
