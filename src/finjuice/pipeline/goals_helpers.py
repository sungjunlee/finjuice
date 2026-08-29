"""Context-surface helpers for goals.yaml.

Owns compact labels, monthly-amount conversion, and safe metadata
serialization. YAML I/O and ``load_goals_file`` stay in
:mod:`finjuice.pipeline.goals`, which re-exports the public names used by
existing callers.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.goals_validators import (
    FinancialContext,
    GoalsDocument,
    KnownObligation,
    MonthlyBudget,
    RecurringSavingsGoal,
    validate_goals_payload,
)


def summarize_active_goals_payload(payload: Any, *, top_n_categories: int = 3) -> list[str]:
    """Return human-readable active goal labels for context surfaces."""
    if isinstance(payload, dict) and "monthly_budget" in payload:
        document, problems = validate_goals_payload(payload)
        if document is not None and not problems:
            labels = [format_monthly_budget_label(document.monthly_budget, top_n_categories)]
            if document.recurring_savings:
                labels.append(format_recurring_savings_label(document.recurring_savings))
            if document.net_worth_target is not None:
                labels.append(format_net_worth_target_label(document.net_worth_target))
            return labels
    return []


def format_monthly_budget_label(monthly_budget: MonthlyBudget, top_n_categories: int = 3) -> str:
    """Build a compact context label for the monthly budget."""
    parts = [
        f"{name} {_format_currency(amount)}"
        for name, amount in sorted(
            monthly_budget.categories.items(),
            key=lambda item: (-item[1], item[0]),
        )[:top_n_categories]
    ]
    label = f"Monthly budget: total {_format_currency(monthly_budget.total)}"
    if parts:
        label += f" ({', '.join(parts)})"
    return label


def format_net_worth_target_label(target: int) -> str:
    """Build a compact context label for the net worth target."""
    return f"Net worth target: {_format_currency(target)}"


def format_recurring_savings_label(
    recurring_savings: list[RecurringSavingsGoal],
    *,
    top_n: int = 3,
) -> str:
    """Build a compact context label for recurring savings targets."""
    total = sum(monthly_amount_for_recurring_savings(goal) for goal in recurring_savings)
    parts = [
        f"{goal.label} {_format_currency(monthly_amount_for_recurring_savings(goal))}/mo"
        for goal in recurring_savings[:top_n]
    ]
    suffix = ""
    if parts:
        suffix = f" ({', '.join(parts)}"
        remaining = len(recurring_savings) - len(parts)
        if remaining > 0:
            suffix += f", +{remaining} more"
        suffix += ")"
    return f"Recurring savings: total {_format_currency(total)}/mo{suffix}"


def monthly_amount_for_recurring_savings(goal: RecurringSavingsGoal) -> int:
    """Return the monthly KRW equivalent for one recurring savings entry."""
    return _monthly_amount(goal.amount, goal.frequency)


def monthly_amount_for_known_obligation(obligation: KnownObligation) -> int:
    """Return the monthly KRW equivalent for one known obligation."""
    return _monthly_amount(obligation.amount, obligation.frequency)


def summarize_financial_metadata_payload(payload: Any) -> dict[str, Any]:
    """Return safe high-level goals.yaml metadata for context surfaces."""
    if not isinstance(payload, dict) or "monthly_budget" not in payload:
        return {}

    document, problems = validate_goals_payload(payload)
    if document is None or problems:
        return {}

    result: dict[str, Any] = {}
    if document.financial_context is not None:
        context_payload = _financial_context_to_dict(document.financial_context)
        if context_payload:
            result["financial_context"] = context_payload

    if document.known_obligations:
        result["known_obligations"] = [
            _known_obligation_to_dict(obligation) for obligation in document.known_obligations
        ]

    return result


def known_obligation_labels(document: GoalsDocument | None) -> set[str]:
    """Return normalized known-obligation labels for candidate suppression."""
    if document is None or not document.known_obligations:
        return set()
    return {obligation.label.strip().casefold() for obligation in document.known_obligations}


def _monthly_amount(amount: int, frequency: str) -> int:
    """Return a monthly KRW equivalent for a recurring amount."""
    multipliers = {
        "weekly": 52 / 12,
        "biweekly": 26 / 12,
        "monthly": 1,
        "quarterly": 1 / 3,
        "yearly": 1 / 12,
    }
    return int(round(amount * multipliers[frequency]))


def _format_currency(amount: int) -> str:
    """Format a KRW integer with separators."""
    return f"₩{amount:,}"


def _financial_context_to_dict(context: FinancialContext) -> dict[str, Any]:
    """Serialize financial context while omitting absent fields."""
    payload: dict[str, Any] = {}
    if context.income is not None:
        income = _compact_dict(
            {
                "monthly_estimate": context.income.monthly_estimate,
                "notes": context.income.notes,
                "source": context.income.source,
                "date": context.income.date,
                "as_of": context.income.as_of,
            }
        )
        if income:
            payload["income"] = income

    if context.family is not None:
        family = _compact_dict(
            {
                "household_size": context.family.household_size,
                "dependents_count": context.family.dependents_count,
                "notes": context.family.notes,
                "source": context.family.source,
                "date": context.family.date,
                "as_of": context.family.as_of,
            }
        )
        if family:
            payload["family"] = family

    if context.housing is not None:
        housing = _compact_dict(
            {
                "status": context.housing.status,
                "monthly_payment": context.housing.monthly_payment,
                "deposit": context.housing.deposit,
                "notes": context.housing.notes,
                "source": context.housing.source,
                "date": context.housing.date,
                "as_of": context.housing.as_of,
            }
        )
        if housing:
            payload["housing"] = housing

    return payload


def _known_obligation_to_dict(obligation: KnownObligation) -> dict[str, Any]:
    """Serialize a known obligation for safe context surfaces."""
    return _compact_dict(
        {
            "label": obligation.label,
            "kind": obligation.kind,
            "category": obligation.category,
            "amount": obligation.amount,
            "frequency": obligation.frequency,
            "monthly_amount": monthly_amount_for_known_obligation(obligation),
            "notes": obligation.notes,
            "source": obligation.source,
            "date": obligation.date,
            "as_of": obligation.as_of,
            "start_month": obligation.start_month,
            "end_month": obligation.end_month,
            "start_date": obligation.start_date,
            "end_date": obligation.end_date,
        }
    )


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without None values."""
    return {key: value for key, value in payload.items() if value is not None}
