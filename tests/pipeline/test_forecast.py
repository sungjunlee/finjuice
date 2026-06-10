"""Unit tests for the deterministic net worth forecast engine."""

from datetime import date
from pathlib import Path

import pytest

from finjuice.pipeline.forecast import (
    SCENARIO_NAMES,
    AssetSwapEvent,
    ForecastResult,
    MonthlyNetExpenseEvent,
    OneTimeExpenseEvent,
    ScenarioAssumptions,
    ScenariosConfig,
    ScenariosConfigValidationError,
    build_forecast,
    load_scenarios_config,
)
from finjuice.pipeline.networth import AggregatedAsset, Liability, ManualAsset, NetWorthPosition


def _position(
    *,
    as_of: date,
    assets: list[AggregatedAsset],
    liabilities: list[Liability] | None = None,
) -> NetWorthPosition:
    total_assets = sum(asset.value for asset in assets)
    resolved_liabilities = list(liabilities or [])
    total_liabilities = sum(liability.principal for liability in resolved_liabilities)
    return NetWorthPosition(
        as_of=as_of,
        assets=assets,
        liabilities=resolved_liabilities,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_worth=total_assets - total_liabilities,
    )


def _uniform_returns(rate: float) -> dict[str, dict[str, float]]:
    return {
        "financial": {scenario_name: rate for scenario_name in SCENARIO_NAMES},
        "real_estate": {scenario_name: 0.0 for scenario_name in SCENARIO_NAMES},
        "deposit": {scenario_name: 0.0 for scenario_name in SCENARIO_NAMES},
        "cash": {scenario_name: 0.0 for scenario_name in SCENARIO_NAMES},
    }


def _build_result(
    *,
    position: NetWorthPosition,
    assumptions: ScenarioAssumptions,
    events: list[object] | None = None,
    years: int = 1,
    target_net_worth: int | None = None,
) -> ForecastResult:
    return build_forecast(
        position,
        ScenariosConfig(
            assumptions=assumptions,
            lifecycle_events=list(events or []),
        ),
        scenario="neutral",
        years=years,
        target_net_worth=target_net_worth,
    )


def test_build_forecast_compounds_assets_and_monthly_savings() -> None:
    """Financial assets and monthly savings should compound deterministically."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=1000.0,
                source="manual",
            )
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=100,
            asset_returns=_uniform_returns(0.12),
            liability_rate_delta=0.0,
        ),
        target_net_worth=5000,
    )

    principal = 1000.0
    projected_savings = 0.0
    for _ in range(12):
        principal = round(principal * 1.01, 2)
        projected_savings = round(projected_savings * 1.01, 2)
        projected_savings = round(projected_savings + 100.0, 2)

    assert len(result.projections) == 13
    assert result.summary.start == "2026-01-01"
    assert result.summary.end == "2027-01-01"
    assert result.summary.end_net_worth == round(principal + projected_savings, 2)
    assert result.summary.target_reached is False
    assert result.summary.target_reached_at is None


def test_build_forecast_applies_lifecycle_events_and_target_tracking() -> None:
    """One-time, recurring, and asset-swap events should all affect the trajectory."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="거주 부동산",
                category="real_estate",
                value=500.0,
                source="manual",
            ),
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=100.0,
                source="manual",
            ),
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=100,
            asset_returns=_uniform_returns(0.0),
            liability_rate_delta=0.0,
        ),
        events=[
            OneTimeExpenseEvent(
                name="Birth",
                date=date(2026, 2, 1),
                one_time_expense=50,
            ),
            MonthlyNetExpenseEvent(
                name="Childcare",
                start=date(2026, 3, 1),
                end=date(2026, 4, 1),
                monthly_net_expense=20,
            ),
            AssetSwapEvent(
                name="Sell Home",
                date=date(2026, 3, 1),
                remove="거주 부동산",
                add=ManualAsset(
                    name="매도 현금",
                    category="financial",
                    value=700.0,
                ),
            ),
        ],
        target_net_worth=900,
    )

    first_month = result.projections[1]
    second_month = result.projections[2]
    third_month = result.projections[3]

    assert first_month.date == "2026-02-01"
    assert first_month.net_worth == 650.0
    assert [event.name for event in first_month.events_fired] == ["Birth"]

    assert second_month.date == "2026-03-01"
    assert second_month.net_worth == 930.0
    assert {event.type for event in second_month.events_fired} == {
        "monthly_net_expense",
        "asset_swap",
    }

    assert third_month.date == "2026-04-01"
    assert third_month.net_worth == 1010.0
    assert [event.type for event in third_month.events_fired] == ["monthly_net_expense"]
    assert result.summary.target_reached is True
    assert result.summary.target_reached_at == "2026-03-01"


def test_load_scenarios_config_allows_signed_lifecycle_cashflows(tmp_path: Path) -> None:
    """Lifecycle events should accept signed net cash-flow amounts."""
    scenarios_file = tmp_path / "scenarios.yaml"
    scenarios_file.write_text(
        """version: 1
assumptions:
  default_savings_per_month: 0
  asset_returns:
    real_estate:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    financial:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    deposit:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    cash:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
  liability_rate_delta: 0.0
lifecycle_events:
  - name: Bonus
    date: 2026-02-01
    one_time_expense: -2000000
  - name: Rent Support
    start: 2026-03-01
    end: 2026-05-01
    monthly_net_expense: -300000
""",
        encoding="utf-8",
    )

    config = load_scenarios_config(scenarios_file)

    one_time_event = config.lifecycle_events[0]
    recurring_event = config.lifecycle_events[1]
    assert isinstance(one_time_event, OneTimeExpenseEvent)
    assert one_time_event.one_time_expense == -2000000
    assert isinstance(recurring_event, MonthlyNetExpenseEvent)
    assert recurring_event.monthly_net_expense == -300000


def test_build_forecast_without_goal_target_leaves_summary_goal_fields_empty() -> None:
    """No-goal forecasts should keep the goal summary fields empty."""
    position = _position(
        as_of=date(2026, 1, 31),
        assets=[
            AggregatedAsset(
                name="Checking",
                category="cash",
                value=500.0,
                source="manual",
            )
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=0,
            asset_returns=_uniform_returns(0.0),
            liability_rate_delta=0.0,
        ),
        target_net_worth=None,
    )

    assert result.projections[1].date == "2026-02-28"
    assert result.summary.target_net_worth is None
    assert result.summary.target_reached is None
    assert result.summary.target_reached_at is None


def test_build_forecast_supports_long_horizons_without_dropping_endpoints() -> None:
    """Long-horizon forecasts should preserve monthly cadence and final endpoints."""
    position = _position(
        as_of=date(2026, 1, 31),
        assets=[
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=1000.0,
                source="manual",
            )
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=50,
            asset_returns=_uniform_returns(0.06),
            liability_rate_delta=0.0,
        ),
        years=10,
        target_net_worth=None,
    )

    assert len(result.projections) == 121
    assert result.projections[1].date == "2026-02-28"
    assert result.projections[-1].date == result.summary.end
    assert result.summary.end == "2036-01-28"


def test_build_forecast_ignores_liability_rate_delta_without_explicit_base_rate() -> None:
    """Rate deltas should not invent interest for liabilities with no declared base rate."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="Checking",
                category="cash",
                value=500.0,
                source="manual",
            )
        ],
        liabilities=[
            Liability(
                name="Family Loan",
                principal=200.0,
                rate=None,
            )
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=0,
            asset_returns=_uniform_returns(0.0),
            liability_rate_delta=0.12,
        ),
        target_net_worth=None,
    )

    assert result.projections[0].total_liabilities == 200.0
    assert result.projections[1].total_liabilities == 200.0


def test_build_forecast_applies_start_date_one_shot_events_to_opening_state() -> None:
    """One-shot events dated at the forecast start should affect the opening snapshot."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=1000.0,
                source="manual",
            ),
            AggregatedAsset(
                name="Condo",
                category="real_estate",
                value=500.0,
                source="manual",
            ),
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=0,
            asset_returns=_uniform_returns(0.0),
            liability_rate_delta=0.0,
        ),
        events=[
            OneTimeExpenseEvent(
                name="Closing Costs",
                date=date(2026, 1, 1),
                one_time_expense=200,
            ),
            AssetSwapEvent(
                name="Sell Condo",
                date=date(2026, 1, 1),
                remove="Condo",
                add=ManualAsset(
                    name="Sale Proceeds",
                    category="cash",
                    value=650.0,
                ),
            ),
        ],
        target_net_worth=None,
    )

    opening = result.projections[0]

    assert opening.date == "2026-01-01"
    assert opening.net_worth == 1450.0
    assert [event.type for event in opening.events_fired] == ["one_time_expense", "asset_swap"]
    assert result.summary.start_net_worth == 1450.0


def test_build_forecast_repeated_one_shot_labels_fire_on_each_date() -> None:
    """Repeated labels should not suppress later one-shot lifecycle events."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=1000.0,
                source="manual",
            )
        ],
    )

    result = _build_result(
        position=position,
        assumptions=ScenarioAssumptions(
            default_savings_per_month=0,
            asset_returns=_uniform_returns(0.0),
            liability_rate_delta=0.0,
        ),
        events=[
            OneTimeExpenseEvent(
                name="Bonus",
                date=date(2026, 2, 1),
                one_time_expense=-100,
            ),
            OneTimeExpenseEvent(
                name="Bonus",
                date=date(2026, 3, 1),
                one_time_expense=-150,
            ),
            AssetSwapEvent(
                name="Rebalance",
                date=date(2026, 4, 1),
                remove="Brokerage",
                add=ManualAsset(
                    name="Deposit A",
                    category="deposit",
                    value=1300.0,
                ),
            ),
            AssetSwapEvent(
                name="Rebalance",
                date=date(2026, 5, 1),
                remove="Deposit A",
                add=ManualAsset(
                    name="Deposit B",
                    category="deposit",
                    value=1600.0,
                ),
            ),
        ],
        target_net_worth=None,
    )

    assert [event.name for event in result.projections[1].events_fired] == ["Bonus"]
    assert [event.name for event in result.projections[2].events_fired] == ["Bonus"]
    assert [event.type for event in result.projections[3].events_fired] == ["asset_swap"]
    assert [event.type for event in result.projections[4].events_fired] == ["asset_swap"]
    assert result.projections[2].net_worth == 1250.0
    assert result.projections[4].net_worth == 1850.0


def test_build_forecast_rejects_asset_swap_remove_target_that_is_missing() -> None:
    """Asset swaps should fail fast when the remove target does not exist."""
    position = _position(
        as_of=date(2026, 1, 1),
        assets=[
            AggregatedAsset(
                name="Brokerage",
                category="financial",
                value=1000.0,
                source="manual",
            )
        ],
    )

    with pytest.raises(ValueError, match="cannot remove missing asset 'Savings'"):
        _build_result(
            position=position,
            assumptions=ScenarioAssumptions(
                default_savings_per_month=0,
                asset_returns=_uniform_returns(0.0),
                liability_rate_delta=0.0,
            ),
            events=[
                AssetSwapEvent(
                    name="Bad Swap",
                    date=date(2026, 2, 1),
                    remove="Savings",
                    add=ManualAsset(
                        name="Deposit",
                        category="deposit",
                        value=1000.0,
                    ),
                )
            ],
            target_net_worth=None,
        )


def test_load_scenarios_config_rejects_ambiguous_lifecycle_event_shapes(tmp_path: Path) -> None:
    """Lifecycle events must declare exactly one event shape."""
    scenarios_file = tmp_path / "scenarios.yaml"
    scenarios_file.write_text(
        """version: 1
assumptions:
  default_savings_per_month: 0
  asset_returns:
    real_estate:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    financial:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    deposit:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    cash:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
  liability_rate_delta: 0.0
lifecycle_events:
  - name: Ambiguous
    date: 2026-02-01
    one_time_expense: 1000000
    asset_swap:
      remove: Brokerage
      add:
        name: Deposit
        category: deposit
        value: 1000000
""",
        encoding="utf-8",
    )

    with pytest.raises(ScenariosConfigValidationError, match="exactly one"):
        load_scenarios_config(scenarios_file)
