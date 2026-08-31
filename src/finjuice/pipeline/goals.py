"""Goals and monthly budget schema helpers.

Compact labels, monthly-amount conversion, and context-surface metadata
helpers live in :mod:`finjuice.pipeline.goals_helpers` and are re-exported
here so existing callers can keep importing from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from finjuice.pipeline.goals_helpers import (
    format_monthly_budget_label,
    format_net_worth_target_label,
    format_recurring_savings_label,
    known_obligation_labels,
    monthly_amount_for_known_obligation,
    monthly_amount_for_recurring_savings,
    summarize_active_goals_payload,
    summarize_financial_metadata_payload,
)
from finjuice.pipeline.goals_validators import (
    FamilyContext,
    FinancialContext,
    GoalsDocument,
    GoalsValidationProblem,
    HousingContext,
    IncomeContext,
    KnownObligation,
    MonthlyBudget,
    RecurringSavingsGoal,
    ValidationProblems,
    _parse_error_problem,
    validate_goals_payload,
    validate_month_literal,
)

__all__ = [
    "FamilyContext",
    "FinancialContext",
    "GoalsDocument",
    "GoalsLoadResult",
    "GoalsValidationProblem",
    "HousingContext",
    "IncomeContext",
    "KnownObligation",
    "MonthlyBudget",
    "RecurringSavingsGoal",
    "ValidationProblems",
    "format_monthly_budget_label",
    "format_net_worth_target_label",
    "format_recurring_savings_label",
    "known_obligation_labels",
    "load_goals_file",
    "load_goals_roundtrip",
    "make_goals_yaml",
    "monthly_amount_for_known_obligation",
    "monthly_amount_for_recurring_savings",
    "new_goals_document",
    "summarize_active_goals_payload",
    "summarize_financial_metadata_payload",
    "validate_goals_payload",
    "validate_month_literal",
    "write_goals_roundtrip",
]


@dataclass(frozen=True)
class GoalsLoadResult:
    """Parse + validation result for goals.yaml."""

    exists: bool
    document: GoalsDocument | None
    problems: ValidationProblems

    @property
    def is_valid(self) -> bool:
        """Return True when the file exists and validates cleanly."""
        return self.exists and self.document is not None and not self.problems


def make_goals_yaml() -> YAML:
    """Create a ruamel.yaml instance configured for round-trip edits."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def new_goals_document() -> CommentedMap:
    """Create a new goals document with the monthly_budget skeleton."""
    monthly_budget = CommentedMap()
    monthly_budget["total"] = 0
    monthly_budget["categories"] = CommentedMap()

    document = CommentedMap()
    document["version"] = 1
    document["monthly_budget"] = monthly_budget
    return document


def load_goals_roundtrip(goals_path: Path) -> tuple[YAML, Any | None]:
    """Load goals.yaml with round-trip support."""
    yaml = make_goals_yaml()
    if not goals_path.exists():
        return yaml, None

    with goals_path.open("r", encoding="utf-8") as handle:
        return yaml, yaml.load(handle)


def write_goals_roundtrip(yaml: YAML, data: CommentedMap, goals_path: Path) -> None:
    """Persist a round-trip goals document."""
    goals_path.parent.mkdir(parents=True, exist_ok=True)
    with goals_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)


def load_goals_file(goals_path: Path) -> GoalsLoadResult:
    """Parse and validate goals.yaml from disk."""
    if not goals_path.exists():
        return GoalsLoadResult(exists=False, document=None, problems=[])

    try:
        _, payload = load_goals_roundtrip(goals_path)
    except (OSError, YAMLError) as exc:
        return GoalsLoadResult(
            exists=True,
            document=None,
            problems=[_parse_error_problem(exc)],
        )

    document, problems = validate_goals_payload(payload)
    return GoalsLoadResult(exists=True, document=document, problems=problems)
