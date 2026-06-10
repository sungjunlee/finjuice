"""Typed goals.yaml validation contracts and models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

MONTH_LITERAL_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_LITERAL_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
RECURRING_SAVINGS_FREQUENCIES = frozenset({"weekly", "biweekly", "monthly", "quarterly", "yearly"})


@dataclass(frozen=True)
class GoalsValidationProblem:
    """One goals.yaml validation problem with optional location metadata."""

    path: str
    message: str
    line: int | None = None
    column: int | None = None

    def format(self) -> str:
        """Render a human-readable validation error."""
        if self.line is not None and self.column is not None:
            return f"Line {self.line}, column {self.column}: {self.path}: {self.message}"
        return f"{self.path}: {self.message}"


ValidationProblems: TypeAlias = list[GoalsValidationProblem]


@dataclass(frozen=True)
class MonthlyBudget:
    """Validated monthly budget document."""

    total: int
    categories: dict[str, int]
    updated: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class RecurringSavingsGoal:
    """One confirmed recurring savings entry from goals.yaml."""

    label: str
    amount: int
    frequency: str = "monthly"
    tags: list[str] | None = None
    notes: str | None = None
    source: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class IncomeContext:
    """Stable high-level income context declared by the user."""

    monthly_estimate: int | None = None
    notes: str | None = None
    source: str | None = None
    date: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class FamilyContext:
    """Stable high-level family/dependent context declared by the user."""

    household_size: int | None = None
    dependents_count: int | None = None
    notes: str | None = None
    source: str | None = None
    date: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class HousingContext:
    """Stable high-level housing context declared by the user."""

    status: str | None = None
    monthly_payment: int | None = None
    deposit: int | None = None
    notes: str | None = None
    source: str | None = None
    date: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class FinancialContext:
    """Optional high-level financial context from goals.yaml."""

    income: IncomeContext | None = None
    family: FamilyContext | None = None
    housing: HousingContext | None = None


@dataclass(frozen=True)
class KnownObligation:
    """One user-confirmed recurring obligation from goals.yaml."""

    label: str
    amount: int
    frequency: str = "monthly"
    kind: str | None = None
    category: str | None = None
    notes: str | None = None
    source: str | None = None
    date: str | None = None
    as_of: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class GoalsDocument:
    """Validated goals.yaml payload."""

    version: int
    monthly_budget: MonthlyBudget
    net_worth_target: int | None = None
    recurring_savings: list[RecurringSavingsGoal] | None = None
    financial_context: FinancialContext | None = None
    known_obligations: list[KnownObligation] | None = None
