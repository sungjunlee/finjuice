"""Forecast inputs selected from one detached repository portfolio revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finjuice.pipeline.forecast import ScenariosConfig, load_scenarios_config_bytes
from finjuice.pipeline.goals import load_goals_roundtrip_bytes, validate_goals_payload
from finjuice.pipeline.networth import NetWorthPosition
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.portfolio_networth import build_repository_networth
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot


@dataclass(frozen=True)
class RepositoryForecastInputs:
    """Validated calculation inputs and their common source metadata."""

    position: NetWorthPosition
    scenarios: ScenariosConfig
    target_net_worth: int | None
    metadata: dict[str, object]


def _selected_bytes(selection: PortfolioConfigSnapshot, kind: str) -> bytes:
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        raise PortfolioDisplayError(f"Repository {kind} configuration requires a valid selection.")
    return head.content


def _scenarios(selection: PortfolioConfigSnapshot) -> ScenariosConfig:
    content = _selected_bytes(selection, "scenarios")
    try:
        return load_scenarios_config_bytes(content)
    except Exception:
        raise PortfolioDisplayError(
            "Selected repository scenarios configuration is invalid."
        ) from None


def _target(selection: PortfolioConfigSnapshot) -> tuple[int | None, str]:
    if selection.selection_state == "absent" and not selection.revisions:
        return None, "canonical_absence_no_target.v1"
    content = _selected_bytes(selection, "goals")
    try:
        _, payload = load_goals_roundtrip_bytes(content)
        document, problems = validate_goals_payload(payload)
        if problems or document is None:
            raise ValueError
        return document.net_worth_target, "selected_goals_config.v1"
    except Exception:
        raise PortfolioDisplayError("Selected repository goals configuration is invalid.") from None


def load_repository_forecast(
    display: PortfolioDisplay, *, as_of: date | None = None
) -> RepositoryForecastInputs:
    """Load required scenarios and optional goals without reopening files or readers."""
    position, metadata = build_repository_networth(display, as_of=as_of)
    scenarios = _scenarios(display.snapshot.scenarios)
    target, goals_policy = _target(display.snapshot.goals)
    return RepositoryForecastInputs(
        position,
        scenarios,
        target,
        {
            **metadata,
            "calculation_policy": "legacy_networth_forecast.v1",
            "scenarios_selection_state": display.snapshot.scenarios.selection_state,
            "scenarios_config_policy": "required_selected_scenarios.v1",
            "goals_selection_state": display.snapshot.goals.selection_state,
            "goals_config_policy": goals_policy,
        },
    )
