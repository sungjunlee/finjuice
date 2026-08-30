"""Section-level validation rules for goals.yaml payload.

Field-level helpers live in ``fields.py`` and are re-exported from this package.
Monthly-budget section helpers live in ``budget.py`` and are re-exported here
so existing callers can keep importing from this module. Financial-context
section helpers live in ``context.py`` and are re-exported the same way.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.goals_validators.budget import (
    _validate_budget_categories,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_budget_category_values,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_budget_notes,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_budget_total,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_budget_updated,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_monthly_budget,
    _validate_monthly_budget_mapping,
)
from finjuice.pipeline.goals_validators.context import (
    _validate_family_context,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_financial_context,
    _validate_housing_context,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_income_context,  # noqa: F401 — re-exported for existing validate.py imports
)
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
    _validate_optional_non_negative_int,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_optional_positive_int,  # noqa: F401 — re-exported for existing validate.py imports
    _validate_optional_string,
    _validate_optional_tags,
    _validate_required_amount,
    _validate_required_label,
)
from finjuice.pipeline.goals_validators.models import (
    MONTH_LITERAL_PATTERN,
    GoalsDocument,
    KnownObligation,
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
