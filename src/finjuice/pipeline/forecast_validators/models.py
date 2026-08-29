"""Typed scenarios.yaml validation contracts and error types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, TypeAlias

from finjuice.pipeline.asset_config import ManualAsset

SCENARIOS_CONFIG_VERSION = 1
SCENARIO_NAMES: tuple[str, ...] = ("conservative", "neutral", "optimistic")

ScenarioName = Literal["conservative", "neutral", "optimistic"]


@dataclass(frozen=True)
class ScenariosConfigIssue:
    """One validation issue for scenarios.yaml."""

    path: str
    message: str
    line: int | None = None
    column: int | None = None

    def format(self) -> str:
        """Return a human-readable error line."""
        location = ""
        if self.line is not None:
            location = f"Line {self.line}"
            if self.column is not None:
                location += f", column {self.column}"
            location += ": "
        return f"{location}{self.path} - {self.message}"


ScenarioValidationIssues: TypeAlias = list[ScenariosConfigIssue]


@dataclass(frozen=True)
class ScenarioAssumptions:
    """Validated forecasting assumptions."""

    default_savings_per_month: int = 0
    asset_returns: dict[str, dict[str, float]] = field(default_factory=dict)
    liability_rate_delta: float = 0.0


@dataclass(frozen=True)
class OneTimeExpenseEvent:
    """One-time cash outflow."""

    name: str
    date: date
    one_time_expense: int


@dataclass(frozen=True)
class MonthlyNetExpenseEvent:
    """Recurring monthly net expense."""

    name: str
    start: date
    end: date | None
    monthly_net_expense: int


@dataclass(frozen=True)
class AssetSwapEvent:
    """Replace one asset with another on a specific date."""

    name: str
    date: date
    remove: str
    add: ManualAsset


LifecycleEvent: TypeAlias = OneTimeExpenseEvent | MonthlyNetExpenseEvent | AssetSwapEvent


@dataclass(frozen=True)
class ScenariosConfig:
    """Validated scenarios.yaml payload."""

    version: int = SCENARIOS_CONFIG_VERSION
    assumptions: ScenarioAssumptions = field(default_factory=ScenarioAssumptions)
    lifecycle_events: list[LifecycleEvent] = field(default_factory=list)


@dataclass(frozen=True)
class ScenariosConfigValidationResult:
    """Validation result for scenarios.yaml."""

    path: Path
    exists: bool
    config: ScenariosConfig
    issues: ScenarioValidationIssues = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when the config is valid or intentionally absent."""
        return not self.issues


class ScenariosConfigValidationError(ValueError):
    """Raised when scenarios.yaml fails schema validation."""

    def __init__(self, path: Path, issues: ScenarioValidationIssues) -> None:
        self.path = path
        self.issues = issues
        lines = "\n".join(f"- {issue.format()}" for issue in issues)
        super().__init__(f"Invalid scenarios.yaml at {path}:\n{lines}")
